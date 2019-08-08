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
def get_db_connection(config) -> ContextManager[mysql.connector.connection.MySQLConnection]:
    con = mysql.connector.connect(**config)
    try:
        yield con
    finally:
        con.close()


class PysmurfArchiverAgent:
    def __init__(self, agent, data_dir=None, targets=[], host=None, user=None):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = self.agent.log
        self.agent.log.
        self.host = host
        self.user = user
        self.data_dir = data_dir
        self.targets = targets

        self.running = False
        self.file_queue = queue.Queue()

        self.agent.register_task('init', self.init, startup=True)
        self.agent.register_process('run', self.run, self.stop)

        self.sql_config = {
            'host': 'database',
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }

    def _new_file_cb(self, _data):
        data, feed_data = _data

        required_keys = {'path', 'format', 'type', 'site', 'pysmurf_instance', 'md5sum'}
        assert required_keys.issubset(data.keys()), f"Data has keys: \n{data.keys()} \n instead of \n{required_keys}"

        self.file_queue.put(data)

    def init(self, session, params=None):
        if params is None:
            params = {}

        targets = params.get('target')
        if targets is None:
            targets = self.targets
        elif type(targets) == str:
            targets = [targets]

        root = self.agent.site_args.address_root
        for t in targets:
            self.agent.subscribe_to_feed(f"{root}.{t}", "pysmurf_files", self._new_file_cb)
            self.log.info(f"Subscribed to {root}.{t}.pysmurf_files")

        # Check if table exits and create it if it doesn't
        with get_db_connection(self.sql_config) as con:
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
                        pysmurf_instance VARCHAR(32),
                        md5sum BINARY(16) NOT NULL
                    );
                """)

                con.commit()
            else:
                self.log.info("Found existing table pysmurf_files.")

        self.agent.start('run', params={})
        return True, "Initialized"

    def _copy_file(self, data, new_path):
        # Copies file over from computer
        cmd = ["rsync"]

        if self.host is not None:
            cmd.append(f"{self.user}@{self.host}:{data['path']}'")
        else:
            cmd.append(data['path'])

        cmd.append(new_path)

        self.log.debug("Running " + " ".join(cmd))
        subprocess.run(cmd)

    def _add_file_to_db(self, cur, d):
        cols = ['path', 'format', 'type', 'site', 'pysmurf_instance', 'md5sum']

        query = f"""
            INSERT INTO pysmurf_files ({', '.join(cols)})  
                VALUES (
                    '{d['path']}', '{d['format']}', '{d['type']}',
                    '{d['site']}', '{d['pysmurf_instance']}', UNHEX('{d['md5sum']}')                    
                )
            """

        try:
            cur.execute(query)
            return True
        except Exception as e:
            self.log.error(f"ERROR!!! Insertion of file {d['path']} into db failed")
            self.log.error(f"Query: {query}")
            self.log.error(e)
            return False

    def run(self, session, params=None):

        self.running = True
        while self.running:
            time.sleep(1)

            if self.file_queue.empty():
                continue

            with get_db_connection(self.sql_config) as con:
                cur = con.cursor()

                while not self.file_queue.empty():
                    d = self.file_queue.get()

                    # File path in archive is:
                    #    data_dir/<5 ctime digits>/<file_type>/<file_name>
                    # For example:
                    #   /data/pysmurf/15647/tuning/1564799250_tuning_b1.txt

                    _, fname = os.path.split(d['path'])

                    ts = time.time()

                    subdir = os.path.join(self.data_dir, f"{str(ts):.5}/{d['type']}")
                    if not os.path.exists(subdir):
                        os.makedirs(subdir)

                    new_path = os.path.join(subdir, fname)

                    self._copy_file(d, new_path)
                    # Verify md5sum

                    # Adds file to database
                    self.log.info("Adding file {} to database".format(
                        d['path']
                    ))
                    self._add_file_to_db(cur, d)

                con.commit()

        return True, "TEST"

    def stop(self, session, params=None):
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

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()