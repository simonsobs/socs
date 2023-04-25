.. highlight:: rst

.. _ifm_sbn246_flowmeter:

======================
SBN246 Flowmeter Agent
======================

The SBN246 Flowmeter Agent is an OCS Agent which monitors flow in gallons per minute 
and temperature in Celsius of the cooling loop of the DRs installed at the site.
Monitoring is performed by connecting the flowmeter device to a DAQ I/O readout device from
the same company, the querying of flowmeter data is done via ModbusTCP connection to that DAQ device.

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

To configure the SBN Flowmeter Agent we need to add a FlowmeterAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'FlowmeterAgent',
       'instance-id': 'flow',
       'arguments': [['--ip-address', '192.168.1.250'],
                     ['--daq-port', '2'],
                     ['--port', '502']]},

.. note::
    The ``-ip--address`` argument should be the ip address of the DAQ device on the network.

Docker Compose
``````````````

The SBN246 Flowmeter Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-ibootbar:
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

The SBN246 Flowmeter is a device from IFM Electronic, and will be used to
monitor the flow and temperature of the cooling loops at the site. This 
monitoring is critical, as any change in flow or temperature will allow SO
to immediately diagnose/anticipate DR behavior. The Agent communicates to
the flowmeter via an AL1340 model of the flowmeter company's (IFM electronic)
IO-Link master with a Modbus TCP interface. The flowmeter plugs into 1 of 4
ports on the DAQ IO-Link device, and the agent queries data directly from
that DAQ port. This is only possible when an ethernet connection is established
via the DAQ IO-Link device's Modbus TCP port (of which there are 2, but only 1
is needed to be in use).


Agent API
---------

.. autoclass:: socs.agents.ifm_sbn246_flowmeter.agent.FlowmeterAgent
    :members:


Supporting APIs
---------------

.. autoclass:: socs.agents.ifm_sbn246_flowmeter.agent
    :members:
    :noindex:
