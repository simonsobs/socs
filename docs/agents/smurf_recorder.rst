.. highlight:: rst

.. _smurf_recorder:

====================
SMuRF Recorder Agent
====================

The SMuRF Recorder Agent is an OCS Agent which listens for G3 Frames
incoming from a G3NetworkSender connection using a G3Reader and writes them to
disk. This is used in conjunction with the SMuRF Streamer to record data from
the SMuRF systems.

.. argparse::
    :filename: ../agents/smurf_recorder/smurf_recorder.py
    :func: make_parser
    :prog: python3 smurf_recorder.py

Description
-----------
The SMuRF Recorder Agent automatically starts listening for a
G3NetworkSender which will send it frames. This will typically be the SMuRF
Streamer. There are several steps performed in a loop, the first of which is an
attempt to read frames from an established connection. A connection attempt is
made if it is not already setup. Meaning it is safe to start the Agent before
a connection is available.

Once a connection is made it will read frames that are sent by the streamer.
Frames should be sent approximately every second. Flow control frames
indicating the connection should stay alive should be sent and are discarded
immediately upon receipt before proceeding to the next step. If the reader
times out then the file will be closed and the reader destroyed, meaning the
connection will need to be reestablished in the next iteration of the loop.
This should be fine, as long as we do not enter a state where many connections
are made in succession.

The recorder will write the frames to file with file names and location based
on the timestamp when the acquisition was started (i.e. the first frame was
written.) Files will be at most "time-per-file" long, which is configurable but
defaults to 10 minutes (the same duration planned for when we are on the
telescope.) Acquisitions that are longer than that will have the same start to
their filenames based on the timestamp when acquisition started, but will
increment a zero padded suffix so one will end up with files like
`2019-01-01-12-00-00_000.g3`, `2019-01-01-12-00-00_001.g3`, etc. for
acquisitions started at 12:00:00 UTC on Jan 1st, 2019.

The recorder handles flow control frames to indicate the start and end of
each acquisition. If a start frame is seen, the currently open file (if there
is one) is closed, and a new file created. If an end frame is seen, the current
file is closed. If frames are seen without a beginning start frame, then they
will be recorded as if a start frame was sent. If a file was started, but no
new frames are acquired for 10 seconds, then the file is closed. A new file
will be created when frames start to come in again. This is an attempt to match
output of other files from the SMuRF, which may be grouped by observation.

Directory location for a group of files will not rotate through a date change,
i.e. if you cross the threshold in ctime between say 15684 and 15685, but are
still on the same acquisition, all files will end up in 15684 to keep them
grouped together.

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the SMuRF Recorder we need to add a SmurfRecorder
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'SmurfRecorder',
       'instance-id': 'smurf-recorder',
       'arguments': [['--auto-start', True],
                     ['--time-per-file', '600'],
                     ['--data-dir', '/data/'],
                     ['--port', '50000'],
                     ['--address', 'smurf-stream-sim']]},

A few things to keep in mind. The ``--data-dir`` is the directory within the
container, the default is probably fine, but can be changed if needed, you'll
just need to mount your directory appropriately when starting the container.
The ``--address`` can be resolved by name if your containers are running within
the same Docker environment, however if your setup differs this likely will be
an IP address, with the container running with the "host" network-mode.

Docker
``````
The SMuRF Recorder should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-smurf-recorder:
    image: simonsobs/ocs-smurf-recorder
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - ./data:/data
    environment:
      LOGLEVEL: "info"

The ``./data`` directory path should point to the location on your host machine
that you want to write the data to. The ``LOGLEVEL`` environment variable can
be used to set the log level for debugging. The default level is "info".

Agent API
---------

.. autoclass:: agents.smurf_recorder.smurf_recorder.SmurfRecorder
    :members: start_recording

Developer Info
--------------
If you're editing the SMuRF Recorder code you might find this info useful.

.. autoclass:: agents.smurf_recorder.smurf_recorder.FrameRecorder
    :members:
