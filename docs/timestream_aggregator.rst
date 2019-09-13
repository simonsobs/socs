.. highlight:: rst

.. _timestream_aggregator:

===========================
Timestream Aggregator Agent
===========================

The Timestream Aggregator Agent is an OCS Agent which listens for G3 Frames
incoming from a G3NetworkSender connection using a G3Reader and writes them to
disk. This is used in conjunction with the SMuRF Streamer to aggregate
timestream data from the SMuRF systems.

.. argparse::
    :filename: ../agents/timestream_aggregator/timestream_aggregator.py
    :func: make_parser
    :prog: python3 timestream_aggregator.py

Description
-----------
The Timestream Aggregator Agent automatically starts listening for a
G3NetworkSender which will send it frames. This will typically be the SMuRF
Streamer. It will keep trying to connect to a sender until it is able to do so,
meaning it is safe to start the Agent before a connection is available.

Once a connection is made it will wait for frames to come in. Once they do, it
will expect frames every second. If the reader times out then the file will be
closed and the Agent will attempt to reestablish a connection. It will write
the frames to file with file names and location based on the timestamp when the
acquisition was started (i.e. the first frame was written.)

Files will be at most "time-per-file" long, which is configurable but defaults
to 10 minutes (the same duration planned for when we are on the telescope.)
Acquisitions that are longer than that will have the same start to their
filenames based on the timestamp when acquisition started, but will increment a
zero padded suffix so one will end up with files like
`2019-01-01-12-00-00_000.g3`, `2019-01-01-12-00-00_001.g3`, etc. for
acquisitions started at 12:00:00 UTC on Jan 1st, 2019.

If a gap in the flow of frames exceeds 5 seconds, then the acquisition is
considered different and the filename timestamp is updated, resulting in a new
base file name. This is an attempt to match output of other files from the
SMuRF, which may be grouped by observation. The time based file rotation should
be a temporary fix until a mechanism for passing when acquisition is started and
stopped is introduced. Directory location for a group of files will not rotate
through a date change, i.e. if you cross the threshold in ctime between say
15684 and 15685, but are still on the same acquisition, all files will end up
in 15684 to keep them grouped together.

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Timestream Aggregator we need to add a TimestreamAggregator
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'TimestreamAggregator',
       'instance-id': 'timestream-agg',
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
The Timestream Aggregator should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  timestream-aggregator:
    image: simonsobs/timestream-aggregator
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

.. autoclass:: agents.timestream_aggregator.timestream_aggregator.TimestreamAggregator
    :members: start_aggregation

Developer Info
--------------
If you're editing the Timestream Aggregator code you might find this info useful.

.. autoclass:: agents.timestream_aggregator.timestream_aggregator.FrameRecorder
    :members:
