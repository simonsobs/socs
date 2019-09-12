from ocs import ocs_agent, site_config
import json
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import datetime

from socs.db import pysmurf_files_manager

from twisted.python.failure import Failure
import os
import mysql.connector
import argparse

from twisted.enterprise import adbapi

from socs.util import get_md5sum

class PysmurfMonitor(DatagramProtocol):
    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log

        self.sql_config = {
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }

        db_host = os.environ.get('MYSQL_HOST')
        if db_host is not None:
            self.sql_config['host'] = db_host

        self.default_params = {
            'create_table': args.create_table
        }

        self.dbpool = adbapi.ConnectionPool('mysql.connector', **self.sql_config)

    def _add_file(self, txn, d):
        dt = datetime.datetime.utcfromtimestamp(d['timestamp'])
        md5sum = get_md5sum(d['path'])
        site, instance_id = self.agent.agent_address.split('.')

        txn.execute(f"""
            INSERT INTO pysmurf_files (
                path, timestamp, format, type, site, 
                instance_id, copied, failed_copy_attempts, md5sum
            )
            VALUES (
                '{d['path']}', '{dt}', '{d['format']}', '{d['type']}', '{site}', 
                '{instance_id}', 0, 0, UNHEX('{md5sum}')                    
            )
        """)
        self.log.info(f"Inserted {d['path']} into database")

        return True

    def _add_file_errback(self, failure: Failure, d):
        self.log.error(f"ERROR!!! {d['path']} was not added to the database")
        return failure

    def datagramReceived(self, _data, addr):
        """Function called whenever data is passed to UDP socket"""
        data = json.loads(_data)

        if data['type'] in ['data_file', 'plot']:
            self.log.info("New file: {fname}", fname=data['payload']['path'])
            d = data['payload']

            deferred = self.dbpool.runInteraction(self._add_file, d)
            deferred.addErrback(self._add_file_errback, d)

    def init(self, session, params=None):
        if params is None:
            params = {}

        for k in ['create_table']:
            if k not in params:
                params[k] = self.default_params[k]

        if params['create_table']:
            try:
                con: mysql.connector.MySQLConnection = self.dbpool.connect()
                cur = con.cursor()
                pysmurf_files_manager.create_table(cur, update=True)
                con.commit()
            finally:
                self.dbpool.disconnect(con)

        return True, "Initialized agent"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Config')
    pgroup.add_argument('--udp-port', type=int,
                        help="Port for upd-publisher")
    pgroup.add_argument('--create-table', type=bool,
                       help="Specifies whether agent should create pysmurf_files"
                            "table if none exist.", default=True)

    return parser


if __name__ == '__main__':
    parser = site_config.add_arguments()

    parser = make_parser(parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'PysmurfMonitor')

    agent, runner = ocs_agent.init_site_agent(args)
    monitor = PysmurfMonitor(agent, args)

    agent.register_task('init', monitor.init, startup=True)

    reactor.listenUDP(args.udp_port, monitor)

    runner.run(agent, auto_reconnect=True)
