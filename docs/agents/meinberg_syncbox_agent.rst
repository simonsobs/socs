.. highlight:: rst

.. _meinberg_syncbox:

====================
Meinberg Syncbox Agent
====================

The Meinberg Syncbox Agent is an OCS Agent which monitors the Meinberg syncbox, the
Monitoring is performed via SNMP.

.. argparse::
    :filename: ../socs/agents/meinberg_syncbox/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Meinberg Syncbox Agent we need to add a MeinbergSyncboxAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'MeinbergSyncboxAgent',
       'instance-id': 'timing-syncbox',
       'arguments': [['--address', '192.168.2.166'],
                     ['--port', 161],
                     ['--mode', 'acq'],
                     ['--snmp-version', 1],
                     ['--outputs', [1, 2, 3]]]},

.. note::
    The ``--address`` argument should be the address of the syncbox on the network.
    This is not the main Meinberg M1000 device.
    The ``--outputs`` argument can be any of the available 3 outputs.

Docker Compose
``````````````

The Meinberg Syncbox Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-timing-syncbox:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=timing-syncbox
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info


The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------
The Meinberg syncbox synchronizes to the M1000 from PTP and distributes signal
to attached devices in various formats (IRIG, PPS, etc).

The Meinberg Syncbox Agent actively issues SNMP GET commands to request the
status from several Object Identifiers (OIDs) specified by the syncbox
provided Management Information Base (MIB).
This MIB has been converted from the original .mib format to a .py format that
is consumable via pysnmp and is provided by socs.

Agent Fields
````````````
The fields returned by the Agent are built from the SNMP GET responses from the
syncbox. The field names consist of the OID name and the last value of the OID,
which often serves as an index for duplicate pieces of hardware that share a
OID string, i.e. redundant outputs on the OID "mbgSyncboxN2XOutputMode". This
results in field names such as "mbgSyncboxN2XOutputMode_1" and
"mbgSyncboxN2XOutputMode_2".

These queries mostly return integers which map to some state. These integers
get decoded into their corresponding string representations and stored in the
OCS Agent Process' session.data object. For more details on this structure, see
the Agent API below. For information about the states corresponding to these
values, refer to the MIB file.

Agent API
---------

.. autoclass:: socs.agents.meinberg_syncbox.agent.MeinbergSyncboxAgent
    :members:

Supporting APIs
----------------

.. autoclass:: socs.agents.meinberg_syncbox.agent.update_cache
    :members:
    :noindex:
