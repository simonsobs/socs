import os
from os import environ

import time
import datetime
import argparse
import txaio

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from spt3g import core


def _create_dirname(start_time, data_dir):
    """Create the file path for .g3 file output.

    Note: This will create directories if they don't exist already.

    Parameters
    ----------
    start_time : float
        Timestamp for start of data collection
    data_dir : str
        Top level data directory for output

    Returns
    -------
    str
        dirname for file for output

    """
    sub_dir = os.path.join(data_dir,
                           "{:.5}".format(str(start_time)))

    # Create new dir for current day
    if not os.path.exists(sub_dir):
        os.makedirs(sub_dir)

    return sub_dir


def _create_file_path(dirname, basename, suffix="", extension="g3"):
    """Create the full path to the output file for writing.

    Parameters
    ----------
    dirname : str
        dirname for output, likely from _create_dirname
    basename : str
        basename of file without extension or suffix
    suffix : str
        Suffix to append to filename (include your own '_')
    extension : str
        file extension to put on file (without '.')

    Returns
    -------
    str
        Full filepath of file for output

    """
    filename = "{}{}.{}".format(basename, suffix, extension)
    filepath = os.path.join(dirname, filename)

    return filepath


class FrameRecorder:
    """Frame recording object. Keeps track of the reader/writer and associated
    information, such as the frames being written to file and the location of
    the output files.

    All of the methods were separated from the loop that ran in the
    TimestreamAggregator OCS Agent. They're meant to be looped over still and
    for that we provide the run() method.

    This class is not safe to run in the twisted reactor, run in a worker
    thread.

    Parameters
    ----------
    file_duration : int
        seconds per file
    tcp_addr : str
        tcp connection address (i.e. "tcp://127.0.0.1:4536")
    data_dir : str
        Location to write data files to. Subdirectories will be created within
        this directory roughly corresponding to one day.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent.

    Attributes
    ----------
    time_per_file : int
        Amount of time in seconds to have in each file. Files will be rotated
        after this many seconds.
    address : str
        Address of the host sending the data via the G3NetworkSender.
    data_dir : str
        Location to write data files to. Subdirectories will be created within
        this directory roughly corresponding to one day.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent.
    reader : spt3g.core.G3Reader
        G3Reader object to read the frames from the G3NetworkSender.
    writer : spt3g.core.G3Writer
        G3Writer for writing the frames to disk.
    frames : list
        List of frames that have been read from the network. Gets cleared after
        writing to file.
    last_meta
        The last meta data Frame passed to the G3Writer. The last meta data
        frame gets written to the top of each file.
    last_frame_write_time : float
        The time at which we wrote the last frame. Used to track when files
        should be rotated between acquisitions.
    last_connection_time : float
        The time at which we last attempted to establish a network connection.
        Used to rate limit the number of attempted connections to the
        G3NetworkSender.
    filename_suffix : int
        For enumerating files within an acquisition. We want to split files in
        10 minute intervals, but the names should remain the same with a
        "_0001" style suffix, which we track with this attribute.
    start_time : float
        Start time of current file. Only agrees with basename time if
        filename_suffix == 0.
    dirname : str
        The directory path currently in use.
    basename : str
        The basename of the file currently being used. The actual file will
        also contain the tracked suffix.

    """
    def __init__(self, file_duration, tcp_addr, data_dir, log):
        # Parameters
        self.time_per_file = file_duration
        self.address = tcp_addr
        self.data_dir = data_dir
        self.log = log

        # Reader/Writer
        self.reader = None
        self.writer = None

        # Attributes
        self.frames = []
        self.last_meta = None
        self.last_frame_write_time = None
        self.last_connection_time = None

        self.filename_suffix = 0
        self.start_time = None
        self.dirname = None
        self.basename = None

    def __del__(self):
        """Clean up by closing out the file once writing is complete."""
        if self.writer is not None:
            self.close_file()

    def _establish_reader_connection(self, timeout=5):
        """Establish the connection to the G3NetworkSender.

        Attempts to connect once and waits if connection could not be made and
        last connection attempt was very recent.

        Parameters
        ----------
        timeout : int
            Timeout in seconds for the G3Reader, afterwhich the connection will
            drop and G3Reader will return empty lists on each Process call.

        Returns
        -------
        reader : spt3g.core.G3Reader
            The G3Reader object connected to the configured address and port

        """
        reader = None
        try:
            reader = core.G3Reader(self.address,
                                   timeout=timeout)
            self.log.info("G3Reader connection established")
        except RuntimeError:
            self.log.error("G3Reader could not connect.")

        # Prevent rapid connection attempts
        if self.last_connection_time is not None:
            t_diff = time.time() - self.last_connection_time
            if t_diff < 1:
                self.log.debug("Last connection was only {d} seconds ago. " +
                               "Sleeping for {t}.", d=t_diff, t=(1 - t_diff))
                time.sleep(1 - t_diff)

        self.last_connection_time = time.time()

        return reader

    def read_frames(self):
        """Establish a connection to the G3NetworkSender if one does not exist,
        then try to read frames from it, discarding any flow control frames.

        Clear internally buffered data and cleanup with call to
        self.close_file() if the reader timesout or has otherwise lost its
        connection.

        """
        # Try to connect if we are not already
        if self.reader is None:
            self.reader = self._establish_reader_connection()

            if self.reader is None:
                return

        self.frames = self.reader.Process(None)
        if self.frames:
            # Handle flow control frames
            for f in self.frames:
                if f.type in [core.G3FrameType.none]:
                    # START; create_new_file
                    if f.get('sostream_flowcontrol') == 1:
                        self.close_file()
                        self.create_new_file()

                    # END; close_file
                    if f.get('sostream_flowcontrol') == 2:
                        self.close_file()

            # Discard flow control frames
            self.frames = [x for x in self.frames if x.type != core.G3FrameType.none]
            return
        else:
            self.log.debug("Could not read frames. Connection " +
                           "timed out, or G3NetworkSender offline. " +
                           "Cleaning up...")
            self.close_file()
            self.reader = None

    def check_for_frame_gap(self, gap_size=5):
        """Check for incoming frame time gap. If frames stop coming in likely
        an acquisition has stopped and we need to rotate files and increment
        our file suffix.

        Rotate files to match data acquisitions (assuming 5 seconds apart or
        more until flow control improved on streaming end).

        Parameters
        ----------
        gap_size : int
            gap size threshold in seconds between frames to check for. Close
            file if exceeded.

        """
        # Don't even try to rotate files if writer not active.
        if self.writer is None:
            self.log.debug("Writer not active, not checking frame gap.")
            return

        if self.last_frame_write_time is not None:
            t_diff = time.time() - self.last_frame_write_time
            if t_diff > gap_size:
                self.log.debug("Last frame written more than {g} seconds " +
                               "ago, rotating file", g=t_diff)
                self.close_file()

    def create_new_file(self):
        """Create a new file if needed.

        This is only done if an existing file is closed out (i.e. writer is
        None). Filename and path will be based on the time the file is made.
        Acquisitions that are grouped together by file duration will share the
        same basename as the start of the acquisition and have their suffix
        incremented.

        Writes the last meta data frame to the start of the file if there is
        one.

        Example:
            # Three 10 minute observations
            file_1 = 2019-08-07-01-30-00_000.g3
            file_2 = 2019-08-07-01-30-00_001.g3
            file_3 = 2019-08-07-01-30-00_002.g3

            # Acqusition stopped and new one started on the hour
            new_file = 2019-08-07-02-00-00_000.g3

        """
        if self.writer is None:
            # Used for tracking when to split acquisitions
            self.start_time = time.time()

            # Only create new dir and basename if we've finished an acquisition
            if self.filename_suffix == 0:
                self.dirname = _create_dirname(self.start_time, self.data_dir)
                self.basename = int(self.start_time)

            suffix = "_{:03d}".format(self.filename_suffix)
            filepath = _create_file_path(self.dirname, self.basename, suffix)
            self.log.info("Writing to file {}".format(filepath))
            self.writer = core.G3Writer(filename=filepath)

            # Write the last metadata frame to the start of the new file
            if self.last_meta is not None:
                self.writer(self.last_meta)

    def write_frames_to_file(self):
        """Write all frames to file.

        Note: Assumes file writer is already instantiated.

        """
        for f in self.frames:
            # Do not record flowcontrol frames
            if f.type == core.G3FrameType.none:
                self.log.warn("Received flow control frame with value {v}." +
                              "Flow control frames should be discarded " +
                              "earlier than this",
                               v=f.get('sostream_flowcontrol'))
                continue

            # Write most recent meta data frame
            if f.type == core.G3FrameType.Observation:
                self.last_meta = f

            self.writer(f)
            self.writer.Flush()
            self.last_frame_write_time = time.time()

        # clear frames list
        self.frames = []

    def split_acquisition(self):
        """Split the acquisition into multiple files based on file_duration.
        Max file length set by file_duration parameter on FrameRecorder object.

        Only rotates if writer currently active.

        """
        if self.writer is None:
            return

        t_diff = time.time() - self.start_time
        if t_diff > self.time_per_file:
            self.log.debug("{s} seconds elapsed since start of file, " +
                           "splitting acquisition", s=t_diff)
            # Flush internal cache and clean-up (no frame written)
            self.writer(core.G3Frame(core.G3FrameType.EndProcessing))
            self.writer = None
            self.filename_suffix += 1

    def close_file(self):
        """Close a file. Clean up with EndProcessing frame, set self.writer to
        None, rezero suffix.

        """
        if self.writer is not None:
            # Flush internal cache and clean-up (no frame written)
            self.writer(core.G3Frame(core.G3FrameType.EndProcessing))
            self.log.debug("File closed.")
        self.writer = None
        self.filename_suffix = 0

    def run(self):
        """Run the DataRecorder, performing all frame collection, file setup,
        file rotation, and writing to file.

        Will only perform actions if frames can be read, with the exception of
        closing the open file if a gap is encountered (i.e. the current
        acquisition has stopped.)

        Meant to be run in a loop.

        """
        self.read_frames()
        self.check_for_frame_gap(10)
        if self.frames:
            self.create_new_file()
            self.write_frames_to_file()
            self.split_acquisition()


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
        self.address = "tcp://{}:{}".format(address, port)
        self.is_streaming = False
        self.log = self.agent.log

    def start_aggregation(self, session, params=None):
        """start_aggregation(params=None)

        OCS Process to start data aggregation. This Process uses FrameRecorder,
        which deals with I/O, requiring this process to run in a worker thread.
        Be sure to register with blocking=True.

        """
        if params is None:
            params = {}

        self.log.info("Data directory set to {}".format(self.data_dir))
        self.log.info("New file every {} seconds".format(self.time_per_file))
        self.log.info("Listening to {}".format(self.address))

        self.is_streaming = True

        recorder = FrameRecorder(self.time_per_file, self.address,
                                 self.data_dir, self.log)

        while self.is_streaming:
            recorder.run()

        # Explicitly clean up when done
        del recorder

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
