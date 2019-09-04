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
                     ['--time-per-file', '3600'],
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

Agent API
---------

.. autoclass:: agents.timestream_aggregator.timestream_aggregator.TimestreamAggregator
    :members: start_aggregation
