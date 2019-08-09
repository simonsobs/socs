import mysql.connector
from contextlib import contextmanager
from ocs import ocs_agent, site_config
import argparse
import os
from typing import ContextManager
import time
import queue
import subprocess


@contextmanager
def get_db_connection(**config) -> ContextManager[mysql.connector.connection.MySQLConnection]:
    """
    Mysql connection context manager.

    Same args as mysql.connector:
    https://dev.mysql.com/doc/connector-python/en/connector-python-connectargs.html
    """
    con = mysql.connector.connect(**config)
    try:
        yield con
    finally:
        con.close()


class PysmurfArchiverAgent:
    """
    Agent to archive pysmurf config files and plots. It should be run on the
    computer where you want files to be archived, and must be on the same
    OCS network as the pysmurf agents that it monitors.

    It creates a table in the mysql docker's `files` database called `pysmurf_files`,
    which contains the path, timestamp, file type, pysmurf agent instance-id, etc.
    of the files its copying over.

    Files must each have a unique filename (not just a unique path), and a
    file type: (tuning, channel_map, final_registers, etc.).
    The file will be copied over to the location:

        data_dir/<5 ctime digits>/<file_type>/<file_name>

    Where data_dir is specified in the site-config or command line. For instance,
    if `data_dir = /data/pysmurf`, tuning dat for band 1 might be written to

        /data/pysmurf/15647/tuning/1564799250_tuning_b1.txt

    Table columns:
        +--------------+-----------------------------------------------------+
        | id (int)     | Primary key of table                                |
        +--------------+-----------------------------------------------------+
        | path         | Path to file                                        |
        +--------------+-----------------------------------------------------+
        | timestamp    | Timestamp file was made                             |
        +--------------+-----------------------------------------------------+
        | format       | File format (txt, npy, yaml, etc)                   |
        +--------------+-----------------------------------------------------+
        | type         | Type of pysmurf file (config, tuning, channel_map)  |
        +--------------+-----------------------------------------------------+
        | site         | Site name                                           |
        +--------------+-----------------------------------------------------+
        | instance_id  | Instance id of agent controlling pysmurf            |
        +--------------+-----------------------------------------------------+
        | md5sum       | md5sum of file                                      |
        +--------------+-----------------------------------------------------+

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
            'host': 'database',
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }

    def _new_file_cb(self, _data):
        """
        Callback for pysmurf_file feeds.
        Checks dict for required keys and puts it into file_queue.
        """
        data, feed_data = _data

        required_keys = {'path', 'format', 'type', 'site', 'instance_id', 'md5sum'}
        assert required_keys.issubset(data.keys()), f"Data is missing keys: {required_keys - data.keys()}"

        self.file_queue.put(data)

    def init(self, session, params=None):
        """
        Initialization task.

        This subscribes to the `pysmurf_files` feed of the agent(s) `target`,
        and calls the `flush_files` op for each to get any cached files.

        It also checks for the existance of the `pysmurf_files` table,
        and creates it if it doesn't exist.

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.

        Parameters:
            target (Union[List, string], optional):
                Pysmurf instance id(s) to monitor for new files.
            run (bool):
                True if run process should be called after initialization.
        """
        if params is None:
            params = {}

        targets = params.get('target')
        if targets is None:
            targets = self.targets
        elif type(targets) == str:
            targets = [targets]

        # Check if table exits and create it if it doesn't
        with get_db_connection(**self.sql_config) as con:
            cur = con.cursor()
            cur.execute("SHOW TABLES;")
            table_names = [x[0] for x in cur.fetchall()]
            if not 'pysmurf_files' in table_names:
                self.log.info("Could not find pysmurf_files table. "
                              "Creating one now....")

                cur.execute("""
                    CREATE TABLE pysmurf_files (
                        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        path VARCHAR(260) NOT NULL,
                        timestamp TIMESTAMP,
                        format VARCHAR(32),
                        type VARCHAR(32),
                        site VARCHAR(32),
                        instance_id VARCHAR(32),
                        md5sum BINARY(16) NOT NULL
                    );
                """)

                con.commit()
            else:
                self.log.info("Found existing table pysmurf_files.")

        # Subscribes to target feeds and calls flush_files
        root = self.agent.site_args.address_root
        for t in targets:
            self.agent.subscribe_to_feed(f"{root}.{t}", "pysmurf_files", self._new_file_cb)
            self.log.info(f"Subscribed to {root}.{t}.pysmurf_files. Flushing files...")
            self.agent.call_op(f"{root}.{t}", 'flush_files', 'start')

        if params.get('run', False):
            self.agent.start('run', params={})

        return True, "Initialized"

    def _copy_file(self, old_path, new_path):
        """
        Copies file from remote computer to host.

        Args:
            old_path (string): Path to file on remote computer
            new_path (string): Path to file on local computer
        """
        # Copies file over from computer
        cmd = ["rsync"]

        if self.host is not None:
            cmd.append(f"{self.user}@{self.host}:{old_path}'")
        else:
            cmd.append(old_path)

        cmd.append(new_path)

        self.log.info(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd)

    def _add_file_to_db(self, cur, d):
        """
        Adds file to database.

        Args:
            cur (mysql cursor): Cursor to database
            d (dict): File data object
        """
        cols = ['path', 'format', 'type', 'site', 'instance_id', 'md5sum']

        query = f"""
            INSERT INTO pysmurf_files ({', '.join(cols)})  
                VALUES (
                    '{d['path']}', '{d['format']}', '{d['type']}',
                    '{d['site']}', '{d['instance_id']}', UNHEX('{d['md5sum']}')                    
                )
            """

        try:
            cur.execute(f"SELECT * FROM pysmurf_files WHERE path='{d['path']}'")
            if cur.fetchone() is not None:
                self.log.warn(f"File {d['path']} already exists in db.")
                return True

            self.log.info(f"Adding file {d['path']} to database")
            cur.execute(query)
            return True
        except Exception as e:
            self.log.error(f"ERROR!!! Insertion of file {d['path']} into db failed")
            self.log.error(f"Query: {query}")
            self.log.error(e)
            return False

    def run(self, session, params=None):
        """
        Run process.

        Loops through file_queue, copying any files over to the local computer
        adding them to the database.
        """
        self.running = True
        while self.running:
            time.sleep(1)

            if self.file_queue.empty():
                continue

            with get_db_connection(**self.sql_config) as con:
                cur = con.cursor()

                while not self.file_queue.empty():
                    d = self.file_queue.get()

                    # Pathname:
                    #   data_dir/<5 ctime digits>/<file_type>/<file_name>
                    _, fname = os.path.split(d['path'])

                    ts = time.time()

                    subdir = os.path.join(self.data_dir, f"{str(ts):.5}/{d['type']}")
                    if not os.path.exists(subdir):
                        os.makedirs(subdir)

                    new_path = os.path.join(subdir, fname)
                    if os.path.exists(new_path):
                        self.log.info(f"Path {new_path} already exists.")
                        continue

                    self._copy_file(d['path'], new_path)

                    # Verify md5sum

                    # Adds file to database
                    self._add_file_to_db(cur, d)

                con.commit()

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

    init_startup = False
    if args.mode == 'init':
        init_startup = True
    elif args.mode == 'run':
        init_startup = {'run': True}


    agent, runner = ocs_agent.init_site_agent(args)

    archiver = PysmurfArchiverAgent(agent, data_dir=args.data_dir,
                                    targets=args.target,
                                    host=args.host)

    agent.register_task('init', archiver.init, startup=init_startup)
    agent.register_process('run', archiver.run, archiver.stop)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
