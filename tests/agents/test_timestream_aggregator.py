import time

import pytest

from socs.agent.timestream_aggregator import FrameRecorder

@pytest.fixture
def frame_recorder(tmpdir):
    p = tmpdir.mkdir("data")
    record = FrameRecorder(10, "tcp://127.0.0.1:4536", p)
    return record


# Test reader connection
class TestReaderConnection():
    ## test successful connection (w/simulator in docker container)
    ## test unsucessfull connection (no simulator running)
    def test_failed_g3reader_connection(self, frame_recorder):
        """Without a backend setup this will fail, though we catch the
        RuntimeError, so it should pass anyway.

        """
        frame_recorder._establish_reader_connection(timeout=1)

    ## test rapid connection attempt (should take a second)
    def test_rapid_reader_connection(self, frame_recorder):
        """Without a backend setup this will fail, though we catch the
        RuntimeError, so it should pass anyway.

        """
        # Fake our last connection time, this should make the check of
        # t_diff < 1 true
        frame_recorder.last_connection_time = time.time()
        frame_recorder._establish_reader_connection(timeout=1)


# test read_frames
## test it establishes a connection if one doesn't exist
## test frames can come in (need simulator sending frames)
## test reader timesout properly

# test write_frames_to_file
## test control frames don't make it into file
## test writing a frame

# test split_acquisition
def test_null_writer_on_split(frame_recorder):
    frame_recorder.split_acquisition()


# test close_file


## Tests below here ##

# test basic initialization
def test_frame_recorder_init(frame_recorder):
    pass

# test check_for_frame_gap
## test if writer is none we don't do anything
def test_check_for_frame_gap(frame_recorder):
    frame_recorder.check_for_frame_gap()
## test we close file if acquisition split by gap size (need simulator running)

# test create_new_file
def test_create_new_file(frame_recorder):
    frame_recorder.create_new_file()
