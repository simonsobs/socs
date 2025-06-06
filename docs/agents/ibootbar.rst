.. highlight:: rst

.. _ibootbar:

====================
iBootbar Agent
====================

The iBootbar Agent is an OCS Agent which monitors and sends commands to the dataprobe
iBoot PDU or iBoot Bar. iBoot Bar is an older device. Monitoring and commanding is
performed via SNMP.

.. argparse::
    :filename: ../socs/agents/ibootbar/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the iBootbar Agent we need to add a ibootbarAgent
block to our ocs configuration file. Here is an example configuration block
for IBoot PDU using all of the available arguments::

      {'agent-class': 'ibootbarAgent',
       'instance-id': 'ibootbar',
       'arguments': [['--address', '10.10.10.50'],
                     ['--port', 161],
                     ['--mode', 'acq'],
                     ['--ibootbar-type', 'IBOOTPDU'],
                     ['--snmp-version', 2]]},

Here is an example configuration block for IBoot Bar using all of the available
arguments::

      {'agent-class': 'ibootbarAgent',
       'instance-id': 'ibootbar',
       'arguments': [['--address', '10.10.10.50'],
                     ['--port', 161],
                     ['--mode', 'acq'],
                     ['--ibootbar-type', 'IBOOTBAR'],
                     ['--snmp-version', 1]]},

.. note::
    The ``--address`` argument should be the address of the iBootbar on the network.

Docker Compose
``````````````

The iBootbar Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-ibootbar:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=ibootbar
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

The iBootbar will be used to power various components on the SO site.
The iBootbar Agent allows the monitoring and commanding of the iBoot PDU.
It monitors the state of each outlet, can set the state of each outlet, can
cycle each outlet, and reboot the system. The iBootbar has an Simple Network
Management Protocol (SNMP) interface.

The iBootbar Agent actively issues SNMP GET commands to request the
status from several Object Identifiers (OIDs) specified by the provided
Management Information Base (MIB). We sample only a subset of the OIDs defined
by the MIB. The MIB has been converted from the original .mib format to a .py
format that is consumable via pysnmp and is provided by socs. The iBootbar
Agent also contains three tasks: set_outlet, cycle_outlet, and set_initial_state.
These tasks issues SNMP SET commands to change the value of OIDs, resulting in
changing the state of outlets.

Agent Fields
````````````

The fields returned by the Agent are built from the SNMP GET responses from the
iBoot PDU. The field names consist of the OID name and the last value of the OID,
which often serves as an index for duplicate pieces of hardware that share a
OID string, i.e. outlets on the OID "outletStatus". This results in field names
such as "outletStatus_0" and "outletStatus_1".

These queries mostly return integers which map to some state. These integers
get decoded into their corresponding string representations and stored in the
OCS Agent Process' session.data object. For more details on this structure, see
the Agent API below. For information about the states corresponding to these
values, refer to the MIB file.

Agent API
---------

.. autoclass:: socs.agents.ibootbar.agent.ibootbarAgent
    :members:

Example Clients
---------------

Below is an example client to control outlets::

    from ocs.ocs_client import OCSClient
    client = OCSClient('ibootbar')

    # Turn outlet on/off
    client.set_outlet(outlet=1, state='off')
    client.set_outlet(outlet=1, state='on')

    # Cycle outlet for 10 seconds
    client.cycle_outlet(outlet=1, cycle_time=10)

    # Set outlets to their initial states
    client.set_initial_state()

Supporting APIs
---------------

.. autoclass:: socs.agents.ibootbar.agent.update_cache
    :members:
    :noindex:
