from ocs import ocs_agent, site_config
import argparse
import os
import time
import queue
import subprocess
from socs.util import get_db_connection, get_md5sum
import binascii
import datetime

from twisted.enterprise import adbapi

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

    """
    def __init__(self, agent, data_dir=None, targets=[], host=None, user=None):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = self.agent.log

        self.host = host
        self.user = user
        self.data_dir = data_dir
        self.targets = targets

        self.running = False
        self.file_queue = queue.Queue()

        self.sql_config = {
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }
        db_host = os.environ.get('MYSQL_HOST')
        if db_host is not None:
            self.sql_config['host'] = db_host

    def _copy_file(self, old_path, new_path):
        """
        Copies file from remote computer to host.
        Called from the worker thread of the `run` process.

        Args:
            old_path (string): Path to file on remote computer
            new_path (string): Path to file on local computer
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

        self.log.info(f"Running: {' '.join(cmd)}")
        subprocess.check_output(cmd)

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

                target_strings = [f"'{t}'" for t in self.targets]
                query = f"""
                    SELECT * FROM pysmurf_files WHERE copied=0 AND
                        instance_id IN ({', '.join(target_strings)})
                """
                cur.execute(query)

                files = cur.fetchall()

                self.log.info(f"Found {len(files)} uncopied files.")

                for f in files:
                    _, fname = os.path.split(f['path'])

                    # Should get the timestamp from db
                    dt = f['timestamp']

                    subdir = os.path.join(self.data_dir,
                                          f"{str(dt.timestamp()):.5}",
                                          f"{f['type']}")

                    if not os.path.exists(subdir):
                        os.makedirs(subdir)

                    new_path = os.path.join(subdir, fname)

                    try:
                        self._copy_file(f['path'], new_path)

                        # Verify md5sum
                        new_md5 = get_md5sum(new_path)
                        if (new_md5 != binascii.hexlify(f['md5sum']).decode()):
                            os.remove(new_path)
                            raise RuntimeError("Copied file failed md5sum verification.")
                        else:
                            self.log.info(f"Sucessfully copied {f['path']} to {new_path}")

                        query = f"""
                            UPDATE pysmurf_files SET path='{new_path}', copied=1 
                            WHERE id={f['id']}
                        """
                        cur.execute(query)

                    except (subprocess.CalledProcessError, RuntimeError) as e:
                        self.log.warn(f"Failed to copy {f['path']}")
                        cur.execute(f"""
                            UPDATE pysmurf_files 
                            SET failed_copy_attempts = failed_copy_attempts + 1
                            WHERE id={f['id']}
                        """)
                        print(e)

                con.commit()

            # This time should probably be set as site-config param
            time.sleep(20)

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
