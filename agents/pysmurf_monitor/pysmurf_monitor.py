import json
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import datetime

import socs
from socs.db import pysmurf_files_manager

from twisted.python.failure import Failure
import os
import argparse

from twisted.enterprise import adbapi

from socs.util import get_md5sum
from ocs.agent.aggregator import Provider

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    import mysql.connector
    from ocs import ocs_agent, site_config


class PysmurfMonitor(DatagramProtocol):
    """
    Monitor for pysmurf UDP publisher.

    This agent should be run on the smurf-server and will monitor messages
    published via the pysmurf Publisher.

    Main functions are making sure registered files make their way to the pysmurf
    files database, and passing session info to pysmurf-controller agents via
    the ``pysmurf_session_data``

    Args:
        agent (ocs.ocs_agent.OCSAgent):
            OCSAgent object
        args (Namespace):
            argparse namespace with site_config and agent specific arguments

    Attributes:
        agent (ocs.ocs_agent.OCSAgent):
            OCSAgent object
        log (txaio.tx.Logger):
            txaio logger object created by agent
        base_file_info (dict):
            shared file info added to all file entries registered by this agent
        dbpool (twisted.enterprise.adbapi.ConnectionPool):
            DB connection pool
    """
    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log

        self.agent.register_feed('pysmurf_session_data')

        self.create_table = bool(args.create_table)

        site, instance = self.agent.agent_address.split('.')
        self.base_file_info = {
            'site': site,
            'instance_id': instance,
            'copied': 0,
            'failed_copy_attempts': 0,
            'socs_version': socs.__version__
        }

        sql_config = {
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }
        db_host = os.environ.get('MYSQL_HOST')
        if db_host is not None:
            sql_config['host'] = db_host

        self.dbpool = adbapi.ConnectionPool('mysql.connector', **sql_config, cp_reconnect=True)

    def _add_file_callback(self, res, d):
        """Callback for when a file is successfully added to DB"""
        self.log.info("Added {} to {}".format(d['path'], pysmurf_files_manager.table))

    def _add_file_errback(self, failure: Failure, d):
        """Errback for when there is an exception when adding file to DB"""
        self.log.error(f"ERROR!!! {d['path']} was not added to the database")
        self.log.error(f"Failure:\n{failure}")

    def datagramReceived(self, _data, addr):
        """
        Called whenever UDP data is received.

        Args:
            _data (str):
                Raw data passed over UDP port. Pysmurf publisher will send a JSON
                string
            addr (tuple):
                (host, port) of the sender.
        """
        data = json.loads(_data)
        pub_id = data['id']

        if data['type'] in ['data_file']:
            self.log.info("New file: {fname}", fname=data['payload']['path'])
            d = data['payload']

            site, instance = self.agent.agent_address.split('.')

            path = d['path']
            if (d['format'] == 'npy') and (not d['path'].endswith('.npy')):
                path += '.npy'

            entry = {
                'path':                 path,
                'action':               d['action'],
                'timestamp':            datetime.datetime.utcfromtimestamp(d['timestamp']),
                'action_timestamp':     d.get('action_ts'),
                'format':               d['format'],
                'plot':                 int(d['plot']),
                'site':                 site,
                'pub_id':               data['id'],
                'instance_id':          instance,
                'copied':               0,
                'failed_copy_attempts': 0,
                'md5sum':               get_md5sum(path),
                'socs_version':         socs.__version__,
            }

            deferred = self.dbpool.runInteraction(pysmurf_files_manager.add_entry, entry)
            deferred.addErrback(self._add_file_errback, d)
            deferred.addCallback(self._add_file_callback, d)

        elif data['type'] == "session_data" or data['type'] == "session_log":
            self.agent.publish_to_feed(
                "pysmurf_session_data", data, from_reactor=True
            )

        # Handles published metadata from the streamer
        elif data['type'] == "metadata":
            self.log.debug("Received Metadata: {payload}", payload=data['payload'])

            # streamer publisher-id looks like `STREAMER:<stream-id>`
            if ':' in pub_id:
                stream_id = pub_id.split(':')[1]
            else:
                # This is so that this still works before people update to the
                # version of the stream fuction where the pub-id is set
                # properly. In this case the stream-id will be something like
                # "unidentified"
                stream_id = pub_id

            path = data['payload']['path']
            val = data['payload']['value']
            val_type = data['payload']['type']

            field_name = Provider._enforce_field_name_rules(path)
            feed_name = f'{stream_id}_meta'

            if feed_name not in self.agent.feeds:
                self.agent.register_feed(feed_name, record=True, buffer_time=0)

            feed_data = {'block_name': field_name,
                         'timestamp': data['time'],
                         'data': {field_name: val}}

            self.agent.publish_to_feed(feed_name, feed_data, from_reactor=True)

    def init(self, session, params=None):
        """init(create_table=True)

        **Task** - Initizes agent by creating / updating the pysmurf_files
        table if requested, and initializing the database connection pool.

        Parameters:
            create_table (bool):
                If true will attempt to create/update pysmurf_files table.

        """
        if params is None:
            params = {}

        if params.get('create_table', self.create_table):
            con: mysql.connector.MySQLConnection = self.dbpool.connect()
            cur = con.cursor()

            try:
                pysmurf_files_manager.create_table(cur, update=True)
                con.commit()
            finally:
                self.dbpool.disconnect(con)

        return True, "Initialized agent"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--udp-port', type=int,
                        help="Port for upd-publisher")
    pgroup.add_argument('--create-table', type=bool,
                        help="Specifies whether agent should create or update "
                             "pysmurf_files table if non exists.", default=True)

    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='PysmurfMonitor', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    monitor = PysmurfMonitor(agent, args)

    agent.register_task('init', monitor.init, startup=True)

    reactor.listenUDP(args.udp_port, monitor)

    runner.run(agent, auto_reconnect=True)
