from socs.agent.timestream_aggregator import FrameRecorder

# Test reader connection
## test successful connection (w/simulator in docker container)
## test unsucessfull connection (no simulator running)
## test rapid connection attempt (should take a second)

# test read_frames
## test it establishes a connection if one doesn't exist
## test frames can come in (need simulator sending frames)
## test reader timesout properly

# test check_for_frame_gap
## test if writer is none we don't do anything
## test we close file if acquisition split by gap size (need simulator running)

# test create_new_file

# test write_frames_to_file
## test control frames don't make it into file
## test writing a frame

# test split_acquisition

# test close_file

def test_frame_recorder_init(tmpdir):
    p = tmpdir.mkdir("data")
    print(p)
    record = FrameRecorder(10, "tcp://127.0.0.1:4536", p)
