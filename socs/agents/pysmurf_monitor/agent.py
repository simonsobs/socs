import argparse
import json
import os
import queue
import time

from ocs import ocs_agent, ocs_feed, site_config
from twisted.internet import reactor
from twisted.internet.protocol import DatagramProtocol

from socs.db.suprsync import SupRsyncFilesManager, create_file


def create_remote_path(meta, archive_name):
    """
    Creates "remote path" for file.

    For pysmurf ancilliary files (in the ``smurf`` archive), paths are
    generated from the pysmurf action / action timestamp::

        <archive_dir>/<5 ctime digits>/<pub_id>/<action_timestamp>_<action>/<plots or outputs>

    For timestream files, the path will be the relative path of the file
    from  whatever the g3_dir is.

    Args
    -----
        meta (dict):
            A dict containing file metadata that's sent from the pysmurf
            publisher when a new file is registered. Contains info such as the
            pysmurf action, file timestamp, path, publisher id, etc.
        archive_name (str):
            Name of the archive the file belongs to. 'smurf' if it is a pysmurf
            ancilliary file, in which case the path will be generated based on
            the pysmurf action / timestamp

    """
    if archive_name == 'smurf':
        ts = meta['timestamp']
        action_timestamp = meta['action_ts']
        action = meta['action']
        basename = os.path.basename(meta['path'])
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
        file_queue (queue.Queue):
            Queue containing metadata for registered files
        db_path (str):
            Path to the suprsync database where files should be entered
        running (bool):
            True if the main process is running.
        echo_sql (bool):
            If True, will echo all sql statements whenever writing to the
            suprsync db.
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
                Raw data passed over UDP port. Pysmurf publisher will send a
                JSON string
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
            data['payload']['type']

            field_name = ocs_feed.Feed.enforce_field_name_rules(path)
            feed_name = f'{stream_id}_meta'

            if feed_name not in self.agent.feeds:
                self.agent.register_feed(feed_name, record=True, buffer_time=0)

            feed_data = {'block_name': field_name,
                         'timestamp': data['time'],
                         'data': {field_name: val}}

            self.agent.publish_to_feed(feed_name, feed_data, from_reactor=True)

    def run(self, session, params=None):
        """run()

        **Process** - Main process for the pysmurf monitor agent. Processes
        files that have been added to the queue, adding them to the suprsync
        database.
        """
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
                    if (meta.get('format') == 'npy') and (not meta['path'].endswith('.npy')):
                        meta['path'] += '.npy'
                    local_path = meta['path']
                    remote_path = create_remote_path(meta, archive_name)

                    # Only delete files that are in timestamped directories
                    # /data/smurf_data/<timestamp> and are not IV, channel
                    # assignment, or tune files. We may want to add more to
                    # this list of "semi-permanent files" later
                    deletable = True
                    if archive_name == 'smurf':
                        if not local_path.split('/')[3].isdigit():
                            deletable = False
                        for key in ["iv", "channel_assignment", "tune"]:
                            if key in local_path:
                                deletable = False

                    files.append(
                        create_file(local_path, remote_path, archive_name,
                                    deletable=deletable)
                    )
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


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='PysmurfMonitor',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    monitor = PysmurfMonitor(agent, args)

    agent.register_process('run', monitor.run, monitor._stop, startup=True)

    reactor.listenUDP(args.udp_port, monitor)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
