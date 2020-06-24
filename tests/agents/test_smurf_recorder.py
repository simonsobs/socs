import time
from unittest.mock import MagicMock

import pytest

from socs.agent.smurf_recorder import FrameRecorder, FlowControl

from spt3g import core


@pytest.fixture
def frame_recorder(tmpdir):
    p = tmpdir.mkdir("data")
    record = FrameRecorder(10, "tcp://127.0.0.1:4536", p)
    return record


@pytest.fixture
def networksender():
    networksender = core.G3NetworkSender(hostname="*", port=4536)
    return networksender


# test basic initialization
def test_frame_recorder_init(frame_recorder):
    pass


# Test reader connection
class TestReaderConnection():
    def test_g3reader_connection(self, frame_recorder, networksender):
        """Test we can establish a connection with a G3NetworkSender."""
        frame_recorder._establish_reader_connection(timeout=1)
        networksender.Close()
        networksender = None

    def test_failed_g3reader_connection(self, frame_recorder):
        """Without a backend setup this will fail, though we catch the
        RuntimeError, so it should pass anyway.

        """
        frame_recorder._establish_reader_connection(timeout=1)

    def test_rapid_reader_connection(self, frame_recorder):
        """Without a backend setup this will fail, though we catch the
        RuntimeError, so it should pass anyway.

        """
        # Fake our last connection time, this should make the check of
        # t_diff < 1 true
        frame_recorder.last_connection_time = time.time()
        frame_recorder._establish_reader_connection(timeout=1)


# test split_acquisition
class TestSplitAcquisition():
    """Splitting an acquisition is time based, and rotates the file we're
    writing to. This class tests various scenarios with this file splitting.

    """
    def test_null_writer_on_split(self, frame_recorder):
        """If writer is None we should just return."""
        frame_recorder.split_acquisition()

    def test_split(self, frame_recorder):
        """We should split if the current time - last file start time is
        greater than the time_per_file set for the frame recorder.

        In this test suite we've set a 10 second time_per_file. Here we mock a
        writer to get passed the writer is None check and force our start_time
        to be well enough in the past to get a file split.

        """
        frame_recorder.writer = MagicMock()
        frame_recorder.start_time = time.time() - 20
        frame_recorder.split_acquisition()

        assert frame_recorder.filename_suffix == 1
        assert frame_recorder.writer is None


# test close_file
def test_close_file(frame_recorder):
    """Test closing out the file and removing the writer."""
    frame_recorder.writer = MagicMock()
    frame_recorder.filename_suffix = 1
    frame_recorder.close_file()

    assert frame_recorder.writer is None
    assert frame_recorder.filename_suffix == 0


# test check_for_frame_gap
class TestFrameGap():
    def test_null_writer_check_for_frame_gap(self, frame_recorder):
        """If writer is None return."""
        frame_recorder.check_for_frame_gap()

    def test_check_for_frame_gap(self, frame_recorder):
        """Mock a writer and test that we detect the gap and close the file."""
        frame_recorder.writer = MagicMock()
        frame_recorder.last_frame_write_time = time.time() - 10
        frame_recorder.check_for_frame_gap()

        assert frame_recorder.writer is None


# test create_new_file
class TestCreateNewFile():
    def test_create_new_file(self, frame_recorder):
        """Writer should be None to create a new file."""
        frame_recorder.create_new_file()

        assert frame_recorder.writer is not None
        assert frame_recorder.start_time is not None

    def test_rapid_create_new_file(self, frame_recorder):
        # Force a quick file creation and remove the writer
        frame_recorder.create_new_file()
        frame_recorder.writer = None

        frame_recorder.create_new_file()

        assert frame_recorder.filename_suffix == 1

    def test_write_last_meta(self, frame_recorder):
        """If last_meta exists, write it to file."""
        f = core.G3Frame(core.G3FrameType.Observation)
        f['session_id'] = 0
        f['start_time'] = time.time()

        frame_recorder.last_meta = f
        frame_recorder.create_new_file()


# test write_frames_to_file
class TestWriteFrames():
    def test_write_flowcontrol_frame(self, frame_recorder):
        """Flow control frames should log a warning and continue."""
        f = core.G3Frame(core.G3FrameType.none)
        f['sostream_flowcontrol'] = FlowControl.START.value

        frame_recorder.frames = [f]
        frame_recorder.write_frames_to_file()

        assert frame_recorder.frames == []

    def test_write_obs_frame(self, frame_recorder):
        """Test writing an observation frame to file."""
        f = core.G3Frame(core.G3FrameType.Observation)
        f['session_id'] = 0
        f['start_time'] = time.time()

        filepath = frame_recorder.create_new_file()
        frame_recorder.frames = [f]
        frame_recorder.write_frames_to_file()

        # Check the frame we wrote
        frames = [fr for fr in core.G3File(filepath)]
        assert len(frames) == 1
        assert frames[0]['session_id'] == 0
        assert frames[0].type is core.G3FrameType.Observation
        assert frame_recorder.last_meta is f


# test read_frames
class TestReadFrames():
    def test_failed_g3reader_connection(self, frame_recorder):
        """Should just return if we can't get a connection.

        """
        frame_recorder.read_frames(1)

    def test_g3reader_connection(self, frame_recorder, networksender):
        """Test we can establish a connection with a G3NetworkSender.

        We aren't sending any frames, so we just make the connection, no frames
        will be processed, so we timeout.

        """
        frame_recorder.read_frames(1)
        networksender.Close()
        networksender = None
        assert frame_recorder.reader is None

    def test_start_frame_processing(self, frame_recorder):
        """Start frame should close the currently open file."""
        frame_recorder.reader = MagicMock()  # mock the reader

        # Make conditions so asserts would fail at end
        frame_recorder.writer = MagicMock()
        frame_recorder.filename_suffix = 1

        f = core.G3Frame(core.G3FrameType.none)
        f['sostream_flowcontrol'] = FlowControl.START.value

        frame_recorder.frames = [f]
        frame_recorder.read_frames()

        assert frame_recorder.writer is None
        assert frame_recorder.filename_suffix == 0

        # check flow control frame discarded
        assert frame_recorder.frames == []

    def test_end_frame_processing(self, frame_recorder):
        """END frame should close the currently open file, and unset the
        last_meta cache.

        """
        frame_recorder.reader = MagicMock()  # mock the reader

        # Make conditions so asserts would fail at end
        frame_recorder.writer = MagicMock()
        frame_recorder.filename_suffix = 1
        frame_recorder.last_meta = 1

        f = core.G3Frame(core.G3FrameType.none)
        f['sostream_flowcontrol'] = FlowControl.END.value

        frame_recorder.frames = [f]
        frame_recorder.read_frames()

        assert frame_recorder.writer is None
        assert frame_recorder.filename_suffix == 0
        assert frame_recorder.last_meta is None

        # check flow control frame discarded
        assert frame_recorder.frames == []

    def test_alive_frame_processing(self, frame_recorder):
        """ALIVE frame should simply be discarded."""
        frame_recorder.reader = MagicMock()  # mock the reader

        f = core.G3Frame(core.G3FrameType.none)
        f['sostream_flowcontrol'] = FlowControl.ALIVE.value

        frame_recorder.frames = [f]
        frame_recorder.read_frames()

        # check flow control frame discarded
        assert frame_recorder.frames == []

    def test_cleanse_frame_processing(self, frame_recorder):
        """CLEANSE frame should simply be discarded."""
        frame_recorder.reader = MagicMock()  # mock the reader

        f = core.G3Frame(core.G3FrameType.Observation)
        f['sostream_flowcontrol'] = FlowControl.CLEANSE.value

        frame_recorder.frames = [f]
        frame_recorder.read_frames()

        # check flow control frame discarded
        assert frame_recorder.frames == []

    def test_improper_flow_control_frames(self, frame_recorder):
        """FlowControl frames are defined as having the key
        'sostream_flowcontrol' in them. Other flow control frame types that
        don't contain 'sostream_flowcontrol' should be recorded, including none
        type frames.

        """
        frame_recorder.reader = MagicMock()  # mock the reader

        f = core.G3Frame(core.G3FrameType.none)
        f['test'] = time.time()

        frame_recorder.frames = [f]
        frame_recorder.read_frames()

        # check flow control frame not discarded
        assert frame_recorder.frames != []
