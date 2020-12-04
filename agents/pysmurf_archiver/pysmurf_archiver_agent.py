import argparse
import os
import time
import queue
import subprocess
from socs.util import get_db_connection, get_md5sum
import binascii
import datetime
from socs.db.pysmurf_files_manager import table as pysmurf_table_name

from twisted.enterprise import adbapi

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


def create_local_path(file, data_dir):
    """
        Creates local path from file database entry.
        If subdirectories do not exist, they will be created.

        The file path will be:

            data_dir/<5 ctime digits>/<pub_id>/<action_timestamp>_<action>/<plots or outputs>

        E.g.

            /data/pysmurf/15647/crate1slot2/1564799250_tune_band/outputs/1564799250_tuning_b1.txt

        In the case of duplicate datafiles being registered, the duplicates
        will still be copied over to the location `new_path_name.{i}` where
        `i` is the next unique index.


        Arguments
        ---------
        file: dict
            Database entry for file.
        data_dir: string
            Path to base directory where files should be copied.

        Returns
        -------
        path: string
            Local pathname for file
    """

    filename = os.path.basename(file['path'])

    dt = file['timestamp']

    action = file['action']

    # First tries to get action timestamp entry
    action_ts = file['action_timestamp']
    if action_ts is None:
        try:
            # If that doesn't exist, try to get the group timestamp from the filename
            action_ts = int(os.path.splitext(filename)[0].split('_')[0])
        except ValueError as e:
            # If that doesn't work, just use the file creation timestamp
            action_ts = str(int(dt.timestamp()))

    dir_type = 'plots' if file['plot'] else 'outputs'

    subdir = os.path.join(
        data_dir,                       # Base directory
        f"{str(dt.timestamp()):.5}",    # 5 ctime digits
        file['pub_id'],                 # publisher id
        f"{action_ts}_{action}",        # grouptime_action
        dir_type,                       # plots/outputs
    )
    new_path = os.path.join(subdir, filename)
    unique_path = new_path
    i = 1
    while os.path.exists(unique_path):
        unique_path = new_path + f'.{i}'
        i += 1
    if unique_path != new_path:
        print(f"Warning! Trying to archive duplicate of {new_path}! "
              f"Will be archived as {unique_path} instead.")

    if not os.path.exists(subdir):
        os.makedirs(subdir)

    return unique_path


class PysmurfArchiverAgent:
    """
    Agent to archive pysmurf config files and plots. It should be run on the
    computer where you want files to be archived, and must have access to the
    database with the `pysmurf_files` table.

    Files must each have a unique filename (not just a unique path), and a
    file type: (tuning, channel_map, final_registers, etc.).
    The file will be copied over to the location:

        data_dir/<5 ctime digits>/<file_type>/<file_name>

    Where data_dir is specified in the site-config or command line. For instance,
    if `data_dir = /data/pysmurf`, tuning dat for band 1 might be written to

        /data/pysmurf/15647/tuning/1564799250_tuning_b1.txt

    Arguments
    ---------
    agent: ocs.ocs_agent.OCSAgent
        OCSAgent object which is running
    data_dir: string
        Path to base directory where files will be copied.
    targets: List[string]
        list of instance-id's of pysmurf-monitors who publish the files
        that should be copied over
    host: string
        Host name of the smurf-server that host original files
    user: string
        username on host to use for copying

    Attributes
    -----------
    agent: ocs.ocs_agent.OCSAgent
        OCSAgent object which is running
    log: txaio.tx.Logger
        txaio logger object created by agent
    data_dir: string
        Path to base directory where files will be copied.
    targets: List[string]
        list of instance-id's of pysmurf-monitors who publish the files
        that should be copied over
    host: string
        Host name of the smurf-server that host original files
    user: string
        username on host to use for copying
    running: bool
        If run task is currently running
    sql_config: dict
        sql login info
    """
    def __init__(self, agent, data_dir=None, targets=[], host=None, user=None):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = self.agent.log

        self.host = host
        self.user = user
        self.data_dir = data_dir
        self.targets = targets

        self.running = False

        self.sql_config = {
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }
        db_host = os.environ.get('MYSQL_HOST')
        if db_host is not None:
            self.sql_config['host'] = db_host

    def _copy_file(self, old_path, new_path, md5sum=None):
        """
        Copies file from remote computer to host.
        Called from the worker thread of the `run` process.

        If md5sum is specified, the md5sum of the new file will be checked against
        the old one. If it does not match, copied file will be deleted.

        Arguments
        ---------
        old_path: string
            Path to file on remote computer
        new_path: string
            Path to file on local computer
        md5sum: string, optional
            md5sum of file on remote computer.

        Returns
        -------
        success: bool
            True if file copied successfully. False otherwise
        """
        # Copies file over from computer
        cmd = ["rsync"]

        fname = old_path
        if self.host is not None:
            fname = f'{self.host}:' + fname
            if self.user is not None:
                fname = f'{self.user}@' + fname

        cmd.append(fname)

        cmd.append(new_path)

        self.log.debug(f"Running: {' '.join(cmd)}")

        try:
            subprocess.check_output(cmd)
        except subprocess.CalledProcessError as e:
            self.log.error("rsync call failed:\n{e}", e=e)
            return False

        # Verify md5sum
        new_md5 = get_md5sum(new_path)
        if new_md5 != md5sum:
            os.remove(new_path)
            self.log.error("{file} copy failed. md5sums do not match.", file=old_path)
            return False

        self.log.debug(f"Successfully copied {old_path} to {new_path}")
        return True


    def run(self, session, params=None):
        """
        Run process.

        Queries database to find any uncopied files from specified targets,
        and attempts to copy them to the local computer. On success, it'll
        update the path to the local path and set `copied=1`. On failure,
        it'll increment the `failed_copy_attempts` counter.
        """
        self.running = True
        while self.running:

            with get_db_connection(**self.sql_config) as con:
                cur = con.cursor(dictionary=True)

                query = """
                    SELECT * FROM {} 
                    WHERE copied=0 AND failed_copy_attempts<5 AND instance_id IN ({})
                """.format(pysmurf_table_name, ", ".join(["%s" for _ in self.targets]))

                cur.execute(query, self.targets)

                files = cur.fetchall()
                if files:
                    self.log.debug(f"Found {len(files)} uncopied files.")

                for f in files:
                    new_path = create_local_path(f, self.data_dir)

                    md5sum = binascii.hexlify(f['md5sum']).decode()
                    if self._copy_file(f['path'], new_path, md5sum=md5sum):
                        # If file copied successfully
                        self.log.debug("Successfully coppied file {}".format(f['path']))
                        query = f"""
                            UPDATE {pysmurf_table_name} SET path=%s, copied=1 
                            WHERE id=%s
                        """
                        cur.execute(query, (new_path, f['id']))
                    else:
                        self.log.debug("Failed to copy {}".format(f['path']))

                        query = f"""
                            UPDATE {pysmurf_table_name} 
                            SET failed_copy_attempts = failed_copy_attempts + 1
                            WHERE id=%s
                        """
                        cur.execute(query, (f['id'],))

                con.commit()

            time.sleep(5)

        return True, "Stopped archiving data."

    def stop(self, session, params=None):
        """ Stopper for run process """
        self.running = False


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Config')
    pgroup.add_argument('--data-dir', type=str,
                        help="Directory where pysmurf data should be copied")
    pgroup.add_argument('--user',  type=str,
                        help="User to connect to use with fsync")
    pgroup.add_argument('--host', type=str,
                        help="host from which files should be copied")
    pgroup.add_argument('--target', nargs="+",
                        help="instance-ids of pysmurf target(s) which should archived")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'run'],
                        help="Initial mode of agent.")

    return parser


def main():
    parser = site_config.add_arguments()
    parser = make_parser(parser)

    args = parser.parse_args()
    site_config.reparse_args(args, 'PysmurfArchiverAgent')

    if args.target is None:
        raise Exception("Argument --target is required")

    if type(args.target) == str:
        args.target = [args.target]
    agent, runner = ocs_agent.init_site_agent(args)

    archiver = PysmurfArchiverAgent(agent, data_dir=args.data_dir,
                                    targets=args.target,
                                    host=args.host)

    agent.register_process('run', archiver.run, archiver.stop, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
