import os
import time
import datetime
import argparse
import txaio

from os import environ

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from spt3g import core


def _create_file_path(start_time, data_dir):
    """Create the file path for .g3 file output.

    Note: This will create directories if they don't exist already.

    Arguments
    ---------
    start_time : float
        Timestamp for start of data collection
    data_dir : str
        Top level data directory for output

    Returns
    -------
    str
        Full filepath of .g3 file for output

    """
    start_datetime = datetime.datetime \
                             .fromtimestamp(start_time,
                                            tz=datetime
                                            .timezone.utc)

    sub_dir = os.path.join(data_dir,
                           "{:.5}".format(str(start_time)))

    # Create new dir for current day
    if not os.path.exists(sub_dir):
        os.makedirs(sub_dir)

    time_string = start_datetime.strftime("%Y-%m-%d-%H-%M-%S")
    filename = "{}.g3".format(time_string)
    filepath = os.path.join(sub_dir, filename)

    return filepath


class TimestreamAggregator:
    """Aggregator for G3 data streams sent over the G3NetworkSender.

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
        Tracks whether or not the aggregator is writing to disk. Setting to
        false stops the aggregation of data.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent

    """

    def __init__(self, agent, time_per_file, data_dir, address="localhost",
                 port=4536):
        self.agent = agent
        self.time_per_file = time_per_file
        self.data_dir = data_dir
        self.address = address
        self.port = port
        self.is_streaming = False
        self.log = self.agent.log

    def start_aggregation(self, session, params=None):
        """start_aggregation(params=None)

        OCS Process to start data aggregation.

        """
        if params is None:
            params = {}

        self.log.info("Data directory set to {}".format(self.data_dir))
        self.log.info("New file every {} seconds".format(self.time_per_file))
        self.log.info("Listening to {}:{}".format(self.address, self.port))

        reader = core.G3Reader("tcp://{}:{}".format(self.address,
                                                    self.port))
        writer = None

        last_meta = None
        self.is_streaming = True
        last_frame_write_time = None

        while self.is_streaming:
            # Currenly this blocks until we get a Frame, thus we'll only write
            # a file once we've started data collection.
            frames = reader.Process(None)

            if last_frame_write_time is not None:
                if (time.time() - last_frame_write_time) > 5:
                    self.log.debug("Last frame written more than 5 seconds " +
                                   "ago, rotating file")
                    writer(core.G3Frame(core.G3FrameType.EndProcessing))
                    writer = None

            if writer is None:
                start_time = time.time()
                filepath = _create_file_path(start_time, self.data_dir)
                self.log.info("Writing to file {}".format(filepath))
                writer = core.G3Writer(filename=filepath)

                # Write the last metadata frame to the start of the new file
                if last_meta is not None:
                    writer(last_meta)

            for f in frames:
                if f.type == core.G3FrameType.Observation:
                    last_meta = f
                writer(f)
                writer.Flush()
                last_frame_write_time = time.time()

            if (time.time() - start_time) > self.time_per_file:
                writer(core.G3Frame(core.G3FrameType.EndProcessing))
                writer = None

        # Once we're done writing close out the file
        if writer is not None:
            writer(core.G3Frame(core.G3FrameType.EndProcessing))
            writer = None

        return True, "Finished aggregation"

    def stop_aggregation(self, session, params=None):
        """stop_aggregation(params=None)

        Stop method associated with start_aggregation process.

        """
        self.is_streaming = False
        return True, "Stopping aggregration"


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

    site_config.reparse_args(args, "TimestreamAggregator")

    agent, runner = ocs_agent.init_site_agent(args)
    listener = TimestreamAggregator(agent,
                                    int(args.time_per_file),
                                    args.data_dir,
                                    address=args.address,
                                    port=int(args.port))

    agent.register_process("stream",
                           listener.start_aggregation,
                           listener.stop_aggregation,
                           startup=bool(args.auto_start))

    runner.run(agent, auto_reconnect=True)
