import json
import time
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor
import datetime
import socs
from socs.util import get_md5sum
import queue
from socs.db.suprsync import SupRsyncFilesManager, SupRsyncFile
import datetime as dt

from socs.util import get_md5sum
from ocs.agent.aggregator import Provider
import os
import argparse

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


def create_remote_path(meta, archive_name):
    """
    <archive_dir>/<5 ctime digits>/<pub_id>/<action_timestamp>_<action>/<plots or outputs>
    """
    if archive_name == 'smurf':
        ts = meta['timestamp']
        action_timestamp = meta['action_ts']
        action = meta['action']
        basename= os.path.basename(meta['path'])
        dir_type = 'plots' if meta['plot'] else 'outputs'
        pub_id = meta['pub_id']

        return os.path.join(
            f"{str(ts):.5}",                 # 5 ctime digits
            pub_id,                          # Pysmurf publisher id
            f"{action_timestamp}_{action}",  # grouptime_action
            dir_type,                        # plots/outputs
            basename,
        )
    elif archive_name == 'timestreams':
        print(meta)
        return str(os.path.join(*os.path.normpath(meta['path']).split(os.sep)[-3:]))


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
        self.file_queue = queue.Queue()
        self.db_path = args.db_path
        self.running = False
        self.echo_sql = args.echo_sql

        self.agent.register_feed('pysmurf_session_data')

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

        if data['type'] in ['data_file', 'g3_file']:
            self.log.info("New file: {fname}", fname=data['payload']['path'])
            data['payload']['pub_id'] = pub_id
            self.file_queue.put(data['payload'])

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

    def run(self, session, params=None):
        srfm = SupRsyncFilesManager(self.db_path, create_all=True, echo=self.echo_sql)

        self.running = True
        session.set_status('running')
        while self.running:
            files = []
            while not self.file_queue.empty():
                meta = self.file_queue.get()
                # Archive name defaults to pysmurf because that is currently
                # the only archive. The smurf-streamer will set the
                # archive_name to "timestreams"
                archive_name = meta.get('archive_name', 'smurf')
                try:
                    local_path = meta['path']
                    remote_path = create_remote_path(meta, archive_name)
                    files.append(SupRsyncFile(
                        local_path=local_path, local_md5sum=get_md5sum(local_path),
                        remote_path=remote_path, archive_name=archive_name,
                        timestamp=dt.datetime.utcnow()
                    ))
                except Exception as e:
                    self.agent.log.error(
                        "Could not generate SupRsync file object from "
                        "metadata:\n{meta}\nRaised Exception: {e}",
                        meta=meta, e=e
                    )

            if files:
                with srfm.Session.begin() as session:
                    session.add_all(files)

            time.sleep(1)


    def _stop(self, session, params=None):
        self.running = False
        session.set_status('stopping')


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--udp-port', type=int,
                        help="Port for upd-publisher")
    pgroup.add_argument('--create-table', type=bool,
                        help="Specifies whether agent should create or update "
                             "pysmurf_files table if non exists.", default=True)
    pgroup.add_argument('--db-path', type=str, default='/data/so/databases/suprsync.db',
                        help="Path to suprsync sqlite database")
    pgroup.add_argument('--echo-sql', action='store_true')
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='PysmurfMonitor', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    monitor = PysmurfMonitor(agent, args)

    agent.register_process('run', monitor.run, monitor._stop, startup=True)

    reactor.listenUDP(args.udp_port, monitor)

    runner.run(agent, auto_reconnect=True)
