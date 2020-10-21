import os
from os import environ

import argparse
import txaio

from socs.agent.smurf_recorder import FrameRecorder

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


class SmurfRecorder:
    """Recorder for G3 data streams sent over the G3NetworkSender.

    This Agent is built to work with the SMuRF data streamer, which collects
    data from a SMuRF blade, packages it into a G3 Frame and sends it over the
    network via a G3NetworkSender.

    We read from the specified address with a G3Reader, and write the data to
    .g3 files on disk.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    time_per_file : int
        Amount of time in seconds to have in each file. Files will be rotated
        after this many seconds
    data_dir : str
        Location to write data files to. Subdirectories will be created within
        this directory roughly corresponding to one day.
    address : str
        Address of the host sending the data via the G3NetworkSender
    port : int
        Port to listen for data on

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    time_per_file : int
        Amount of time in seconds to have in each file. Files will be rotated
        after this many seconds.
    data_dir : str
        Location to write data files to. Subdirectories will be created within
        this directory roughly corresponding to one day.
    address : str
        Address of the host sending the data via the G3NetworkSender.
    port : int
        Port to listen for data on.
    is_streaming : bool
        Tracks whether or not the recorder is writing to disk. Setting to
        false stops the recording of data.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    target_rate : float
        Target sampling rate for monitored channels.
    monitored_channels : list
        Readout channels to monitor. Incoming data for these channels will be
        downsampled and published to an OCS feed.
    """

    def __init__(self, agent, time_per_file, data_dir, stream_id,
                 address="localhost", port=4536, target_rate=10):
        self.agent = agent
        self.time_per_file = time_per_file
        self.data_dir = data_dir
        self.stream_id = stream_id
        self.address = "tcp://{}:{}".format(address, port)
        self.is_streaming = False
        self.log = self.agent.log
        self.target_rate = target_rate
        self.monitored_channels = []

        self.agent.register_feed('detectors', record=True)

    def set_monitored_channels(self, session, params=None):
        """Sets channels that the recorder should monitor.

        Args
        -----
        channels : list, required
            List of channel numbers to be monitored.
        """
        if params is None:
            params = {}

        self.monitored_channels =  params['channels']
        return True, f"Set monitored channels to {self.monitored_channels}"

    def set_target_rate(self, session, params=None):
        """Sets the target sample rate for monitored channels.

        Args
        -----
        target_rate : float, required
            Target rate after downsampling for monitored channels in Hz.
        """
        if params is None:
            params = {}

        self.target_rate = params['target_rate']
        return True, f"Set target sampling rate to {self.target_rate}"

    def start_record(self, session, params=None):
        """start_record(params=None)

        OCS Process to start recording SMuRF data. This Process uses
        FrameRecorder, which deals with I/O, requiring this process to run in a
        worker thread. Be sure to register with blocking=True.

        """
        if params is None:
            params = {}

        self.log.info("Data directory set to {}".format(self.data_dir))
        self.log.info("New file every {} seconds".format(self.time_per_file))
        self.log.info("Listening to {}".format(self.address))

        self.is_streaming = True

        recorder = FrameRecorder(self.time_per_file, self.address,
                                 self.data_dir, self.stream_id,
                                 target_rate=self.target_rate)

        while self.is_streaming:
            recorder.monitored_channels = self.monitored_channels
            recorder.target_rate = self.target_rate
            recorder.run()
            for k, v in recorder.stream_data.items():
                if v['timestamps']:
                    self.agent.publish_to_feed('detectors', v)

        # Explicitly clean up when done
        del recorder

        return True, "Finished Recording"

    def stop_record(self, session, params=None):
        """stop_record(params=None)

        Stop method associated with start_record process.

        """
        self.is_streaming = False
        return True, "Stopping Recording"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--auto-start", default=False, type=bool,
                        help="Automatically start listening for data at " +
                        "Agent startup.")
    pgroup.add_argument("--time-per-file", default=600,
                        help="Amount of time in seconds to put in each file.")
    pgroup.add_argument("--data-dir", default="/data/",
                        help="Location of data directory.")
    pgroup.add_argument("--port", default=50000,
                        help="Port to listen on.")
    pgroup.add_argument("--address", default="localhost",
                        help="Address to listen to.")
    pgroup.add_argument('--stream-id', default='None',
                        help="Stream id of recorded stream. If one is not "
                             "present in the G3Frames, this is the stream-id"
                             "that will be used to determine file paths.")
    pgroup.add_argument('--target-rate', default=10, type=float,
                       help="Target rate for monitored readout channels in "
                            "Hz. This willl be the rate that detector data is "
                            "streamed to an OCS feed")

    return parser


if __name__ == "__main__":
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='SmurfRecorder', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    listener = SmurfRecorder(agent,
                             int(args.time_per_file),
                             args.data_dir,
                             args.stream_id,
                             address=args.address,
                             port=int(args.port),
                             target_rate=args.target_rate)

    agent.register_process("record",
                           listener.start_record,
                           listener.stop_record,
                           startup=bool(args.auto_start))
    agent.register_task('set_monitored_channels',
                        listener.set_monitored_channels)
    agent.register_task('set_target_rate', listener.set_target_rate)


    runner.run(agent, auto_reconnect=True)
