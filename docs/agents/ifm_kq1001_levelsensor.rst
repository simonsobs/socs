.. highlight:: rst

.. _ifm_kq1001_levelsensor:

=============================
IFM KQ1001 Level Sensor Agent
=============================

The IFM KQ1001 Level Sensor Agent is an OCS Agent which monitors the
fluid level in percent reported by the sensor.  The agent also records
the device status of the KQ1001 sensor.  Monitoring is performed by
connecting the level sensor device to an IO-Link master device from
the same company; the querying of level sensor data is done via HTTP
requests to the IO-Link master.

.. argparse::
    :filename: ../socs/agents/ifm_kq1001_levelsensor/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the IFM KQ1001 Level Sensor Agent we need to add a
LevelSensorAgent block to our ocs configuration file. Here is an
example configuration block using all of the available arguments::

      {'agent-class': 'LevelSensorAgent',
       'instance-id': 'level',
       'arguments': [['--ip-address', '10.10.10.159'],
                     ['--daq-port', '2']]},

.. note::
    The ``--ip-address`` argument should use the IP address of the IO-Link
    master.

Docker Compose
``````````````

The IFM KQ1001 Level Sensor Agent should be configured to run in a
Docker container. An example docker compose service configuration is
shown here::

  ocs-level:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=level
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

The KQ1001 Level Sensor is a device from IFM Electronic, and can be
used to monitor the level of a process fluid (like water) in a
nonconductive tank through the tank wall.  The sensor can be
noninvasively taped to the outside of the tank.  The sensor must be
calibrated to the tank before it can report level readings.  The
calibration is best if performed on the tank when it is empty or full,
but can also be performed if the tank is partially full.  For more
information on the calibration, see the operating instructions for the
KQ1001, available on the IFM website.  The Agent communicates with the
level sensor via an AL1340 IFM Electronic device--an IO-Link master
from which the agent makes HTTP requests. The level sensor plugs into
1 of 4 ports on the IO-Link master, and the agent queries data
directly from that IO-Link master port.  This is only possible when an
ethernet connection is established via the IO-Link master's IoT port.

IO-Link Master Network
```````````````````````
Once plugged into the IoT port on your IO-Link master, the IP address of the
IO-Link master is automatically set by a DHCP server in the network. If no DHCP
server is reached, the IP address is automatically assigned to the factory setting
for the IoT port (169.254.X.X).

IO-Link Visualization Software
```````````````````````````````
A Windows software called LR Device exists for parameter setting and visualization
of IO-Link master and device data. The software download link is below should the
user need it for changing settings on the IO-Link master. On the LR Device software
panel, click the 'read from device' button on the upper right (leftmost IOLINK
button); the software will then search for the IO-Link master. Once found, it will
inform the user of the IO-Link master model number (AL1340) and its IP address.

 - `LR Device Software <https://www.ifm.com/de/en/download/LR_Device>`_

Agent API
---------

.. autoclass:: socs.agents.ifm_kq1001_levelsensor.agent.LevelSensorAgent
    :members:
