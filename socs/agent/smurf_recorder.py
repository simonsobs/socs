import os
from enum import Enum

import time
import txaio
import numpy as np
import socket

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    import so3g
    from spt3g import core


class FlowControl(Enum):
    """Flow control enumeration."""
    ALIVE = 0
    START = 1
    END = 2
    CLEANSE = 3


def _create_dirname(start_time, data_dir, stream_id):
    """Create the file path for .g3 file output.

    Note: This will create directories if they don't exist already.

    Parameters
    ----------
    start_time : float
        Timestamp for start of data collection
    data_dir : str
        Top level data directory for output
    stream_id : str
        Stream id of collection

    Returns
    -------
    str
        dirname for file for output

    """
    sub_dir = os.path.join(data_dir,
                           "{:.5}".format(str(start_time)),
                           stream_id)

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
    stream_id : str
        Stream ID to use to determine file path if one is not found in frames.

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
        txaio logger object.
    reader : spt3g.core.G3Reader
        G3Reader object to read the frames from the G3NetworkSender.
    writer : spt3g.core.G3Writer
        G3Writer for writing the frames to disk.
    data_received : bool
        Whether data has been received by the current instance of the G3Reader.
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
    _last_file_timestamp : int
        Timestamp of last filename. Used to check if a new file was started
        within the same second a new file is being made to avoid naming
        conflicts.
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
    monitored_channels : list
        List of readout channels to be monitored. Data from these channels will
        be stored in ``stream_data`` after each ``run`` function call.
    target_rate : float
        Target sampling rate for monitored channels in Hz.
    stream_data : dict
        Data containing downsampled timestream data from the monitored. This
        dict will have the channel name (such as ``r0012``) as the key, and
        the values will have the structure required by the OCS_Feed.
    """
    def __init__(self, file_duration, tcp_addr, data_dir, stream_id,
                 target_rate=10):
        # Parameters
        self.time_per_file = file_duration
        self.address = tcp_addr
        self.data_dir = data_dir
        self.stream_id = stream_id
        self.log = txaio.make_logger()

        # Reader/Writer
        self.reader = None
        self.writer = None
        self.data_received = False

        # Attributes
        self.frames = []
        self.last_meta = None
        self.last_frame_write_time = None
        self.last_connection_time = None
        self._last_file_timestamp = None

        self.filename_suffix = 0
        self.start_time = None
        self.dirname = None
        self.basename = None

        self.monitored_channels = []
        self.target_rate = target_rate
        self.stream_data = {}

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
            self.log.debug("G3Reader connection to {addr} established!",
                           addr=self.address)
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

    def read_frames(self, timeout=5):
        """Establish a connection to the G3NetworkSender if one does not exist,
        then try to read frames from it, discarding any flow control frames.

        Clear internally buffered data and cleanup with call to
        self.close_file() if the reader timesout or has otherwise lost its
        connection.

        Parameters
        ----------
        timeout : int
            Timeout in seconds for establishing the G3Reader connection.

        """
        # Try to connect if we are not already
        if self.reader is None:
            self.reader = self._establish_reader_connection(timeout)

            if self.reader is None:
                return

        # Allows tests to Mock a reader
        if type(self.reader) is core.G3Reader:
            self.frames = self.reader.Process(None)

        if self.frames:
            # Handle flow control frames
            for f in self.frames:
                flow = f.get('sostream_flowcontrol')

                if flow is not None:
                    # START; create_new_file
                    if FlowControl(flow) is FlowControl.START:
                        self.close_file()

                    # END; close_file
                    if FlowControl(flow) == FlowControl.END:
                        self.close_file()
                        self.last_meta = None

                    # ALIVE and CLEANSE; do nothing
                    if FlowControl(flow) is FlowControl.CLEANSE:
                        self.log.debug("I saw a CLEANSE frame.")

            # Discard all flow control frames
            self.frames = [x for x in self.frames if 'sostream_flowcontrol' not in x]
            # Discard Pipeline info frame
            self.frames = [x for x in self.frames
                           if x.type != core.G3FrameType.PipelineInfo]
            if self.frames and not self.data_received:
                self.data_received = True
                self.log.info("Started receiving frames from {addr}",
                              addr=self.address)
            return
        else:
            if self.data_received:
                self.log.info("Could not read frames. Connection " +
                              "timed out, or G3NetworkSender offline. " +
                              "Cleaning up...")
            self.close_file()
            self.data_received = False
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

            # Avoid duplicate filenames if new file started within 1 sec
            if self._last_file_timestamp is None:
                pass
            elif int(self.start_time) == self._last_file_timestamp:
                self.log.debug("New file started within 1 second of previous " +
                               "file, incrementing filename suffix.")
                self.filename_suffix += 1

            # Only create new dir and basename if we've finished an acquisition
            if self.filename_suffix == 0:
                stream_id = self.stream_id
                for f in self.frames:
                    if f.get('sostream_id') is not None:
                        stream_id = f['sostream_id']
                        break

                self.dirname = _create_dirname(self.start_time,
                                               self.data_dir,
                                               stream_id)
                self.basename = int(self.start_time)

            suffix = "_{:03d}".format(self.filename_suffix)
            filepath = _create_file_path(self.dirname, self.basename, suffix)
            self.log.info("Writing to file {}".format(filepath))
            self.writer = core.G3Writer(filename=filepath)
            self._last_file_timestamp = int(self.start_time)

            # Write the last metadata frame to the start of the new file
            if self.last_meta is not None:
                self.writer(self.last_meta)

            return filepath

    def write_frames_to_file(self):
        """Write all frames to file.

        Note: Assumes file writer is already instantiated.

        """
        for f in self.frames:
            # Make sure we do not record flowcontrol frames
            flow = f.get('sostream_flowcontrol')
            if flow is not None:
                self.log.warn("Received flow control frame with value {v}. " +
                              "Flow control frames should be discarded " +
                              "earlier than this", v=flow)
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
        if len(self.monitored_channels) > 0:
            try:
                self.read_stream_data()
            except Exception as e:
                self.log.warn("Exception thrown when reading stream data:\n{e}", e=e)

        if self.frames:
            self.create_new_file()
            self.write_frames_to_file()
            self.split_acquisition()

    def read_stream_data(self):
        """Reads stream data from ``self.frames``, downsamples it, and stores
        it in ``self.stream_data``.
        """
        chan_keys = [f'r{c:04}' for c in self.monitored_channels]
        self.stream_data = {
            k: {'timestamps': [], 'block_name': k, 'data': {k:[]}}
            for k in chan_keys
        }

        for frame in self.frames:
            if frame.type != core.G3FrameType.Scan:
                continue
            ds_factor = (frame['data'].sample_rate/core.G3Units.Hz) \
                        // self.target_rate
            if np.isnan(ds_factor):
                continue
            ds_factor = max(int(ds_factor), 1)
            n_samples = frame['data'].n_samples
            if 1 < n_samples <= ds_factor:
                ds_factor = n_samples - 1
            times = [
                t.time / core.G3Units.s
                for t in frame['data'].times()[::ds_factor]
            ]
            for key in chan_keys:
                data = frame['data'].get(key)
                if data is None:
                    continue
                self.stream_data[key]['timestamps'].extend(times)
                self.stream_data[key]['data'][key].extend(list(data[::ds_factor]))

