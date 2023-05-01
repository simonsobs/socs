.. highlight:: rst

.. _ifm_sbn246_flowmeter:

==========================
IFM SBN246 Flowmeter Agent
==========================

The IFM SBN246 Flowmeter Agent is an OCS Agent which monitors flow in liters
per minute and temperature in Celsius of the cooling loop of the DRs installed
at the site. Monitoring is performed by connecting the flowmeter device to an
IO-Link master device from the same company; the querying of flowmeter data is
done via HTTP requests to the IO-Link master.

.. argparse::
    :filename: ../socs/agents/ifm_sbn246_flowmeter/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the IFM SBN246 Flowmeter Agent we need to add a FlowmeterAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'FlowmeterAgent',
       'instance-id': 'flow',
       'arguments': [['--ip-address', '10.10.10.159'],
                     ['--daq-port', '2']]},

.. note::
    The ``--ip-address`` argument should use the IP address of the IO-Link
    master.

Docker Compose
``````````````

The IFM SBN246 Flowmeter Agent should be configured to run in a Docker
container. An example docker-compose service configuration is shown here::

  ocs-flow:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=flow
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

The SBN246 Flowmeter is a device from IFM Electronic, and is used to
monitor the flow and temperature of the cooling loops at the site. This
monitoring is critical, as any change in flow or temperature allows us
to immediately diagnose/anticipate DR behavior. The Agent communicates with
the flowmeter via an AL1340 IFM Electronic device--an IO-Link master from which the
agent makes HTTP requests. The flowmeter plugs into 1 of 4 ports on the IO-Link
master, and the agent queries data directly from that IO-Link master port.
This is only possible when an ethernet connection is established via the IO-Link
master's IoT port.

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

.. autoclass:: socs.agents.ifm_sbn246_flowmeter.agent.FlowmeterAgent
    :members:
