.. highlight:: rst

.. _ifm_iolink_master:

=========================
IFM IO-Link Master Agent
=========================

The IFM IO-Link Master Agent is an OCS Agent which monitors IO-Link sensors
connected to an IFM DataLine IO-Link master (AL1340, AL1342, or compatible
models). It reads all configured ports in a single HTTP request using a
persistent connection, avoiding the connection churn that can cause device
lockups.

.. argparse::
    :filename: ../socs/agents/ifm_iolink_master/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the IFM IO-Link Master Agent we need to add an
IFMIOLinkMasterAgent block to our ocs configuration file. Here is an example
configuration block using all of the available arguments::

      {'agent-class': 'IFMIOLinkMasterAgent',
       'instance-id': 'iolink-cryo1',
       'arguments': [['--ip-address', '10.10.10.159'],
                     ['--port', '1:SBN246'],
                     ['--port', '2:KQ1001']]},

For an AL1342 (8-port model) with multiple sensors::

      {'agent-class': 'IFMIOLinkMasterAgent',
       'instance-id': 'iolink-platform2',
       'arguments': [['--ip-address', '10.10.10.160'],
                     ['--port', '1:SBN246'],
                     ['--port', '2:SBN246'],
                     ['--port', '5:KQ1001'],
                     ['--port', '7:KQ1001'],
                     ['--sample-freq', '0.5']]},

.. note::
    The ``--ip-address`` argument should use the IP address of the IO-Link
    master's IoT port. The ``--port`` argument is repeated for each IO-Link
    port that has a sensor connected, in the format ``PORT_NUM:SENSOR_TYPE``.

Docker Compose
``````````````

The IFM IO-Link Master Agent should be configured to run in a Docker
container. An example docker compose service configuration is shown here::

  ocs-iolink-cryo1:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=iolink-cryo1
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

This agent communicates with IFM DataLine IO-Link masters (AL1340, AL1342,
and other models sharing the same IoT Core REST API) to read sensor data from
connected IO-Link devices. It replaces the per-sensor agent model (separate
agents for flowmeters, level sensors, etc.) with a single agent per IO-Link
master that reads all ports efficiently.

Key Features
````````````

- **Single persistent HTTP connection**: Uses HTTP keep-alive to maintain one
  TCP connection, eliminating the connection churn that causes device lockups.
- **Batch port reading**: Uses the ``getdatamulti`` API to read all configured
  ports in a single HTTP round-trip.
- **Automatic reconnection**: On connection failure, the agent reconnects and
  retries once before marking the connection as lost.
- **Model-agnostic**: Works with any IFM DataLine IO-Link master that
  implements the IoT Core REST API (firmware 3.1.x).
- **Extensible sensor support**: New sensor types can be added by writing a
  single extraction function in ``drivers.py``.

Supported Sensor Types
``````````````````````

- ``SBN246``: Flowmeter — reports flow (liters/min) and temperature (Celsius)
- ``KQ1001``: Level sensor — reports level (%) and device status
- ``generic``: Raw hex passthrough for unsupported sensor types

IO-Link Master Network
``````````````````````

Once plugged into the IoT port on your IO-Link master, the IP address of the
IO-Link master is automatically set by a DHCP server in the network. If no DHCP
server is reached, the IP address is automatically assigned to the factory
setting for the IoT port (169.254.X.X).

Agent API
---------

.. autoclass:: socs.agents.ifm_iolink_master.agent.IFMIOLinkMasterAgent
    :members:
