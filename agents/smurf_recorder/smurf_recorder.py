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

    """

    def __init__(self, agent, time_per_file, data_dir, address="localhost",
                 port=4536):
        self.agent = agent
        self.time_per_file = time_per_file
        self.data_dir = data_dir
        self.address = "tcp://{}:{}".format(address, port)
        self.is_streaming = False
        self.log = self.agent.log

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
                                 self.data_dir)

        while self.is_streaming:
            recorder.run()

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

    return parser


if __name__ == "__main__":
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    # Get the default ocs agrument parser
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    # Parse commandline
    args = parser.parse_args()

    site_config.reparse_args(args, "SmurfRecorder")

    agent, runner = ocs_agent.init_site_agent(args)
    listener = SmurfRecorder(agent,
                             int(args.time_per_file),
                             args.data_dir,
                             address=args.address,
                             port=int(args.port))

    agent.register_process("record",
                           listener.start_record,
                           listener.stop_record,
                           startup=bool(args.auto_start))

    runner.run(agent, auto_reconnect=True)
