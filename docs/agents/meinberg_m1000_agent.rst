.. _meinberg_m1000:

====================
Meinberg M1000 Agent
====================

The Meinberg M1000 Agent is an OCS Agent which monitors the Meinberg M1000, the
main source of timing for the SO site. Monitoring is performed via SNMP.

.. argparse::
    :filename: ../socs/agents/meinberg_m1000/agent.py
    :func: make_parser
    :prog: python3 agent.py

Description
-----------
The Meinberg M1000 is a critical piece of hardware, it provides the precise
timing information distributed among the SO site. The M1000 synchronizes to GPS
and distributes timing mostly over the network using PTP. The M1000 has an
Simple Network Management Protocol (SNMP) interface, allowing one to monitor
the state of the device.

The Meinberg M1000 Agent actively issues SNMP GET commands to request the
status from several Object Identifiers (OIDs) specified by the Meinberg
provided Management Information Base (MIB). We sample only a subset of the OIDs
defined by the MIB, following recommendations from the `M1000 manual`_.
This MIB has been converted from the original .mib format to a .py format that
is consumable via pysnmp and is provided by socs.

Agent Fields
````````````
The fields returned by the Agent are built from the SNMP GET responses from the
M1000. The field names consist of the OID name and the last value of the OID,
which often serves as an index for duplicate pieces of hardware that share a
OID string, i.e. redundant power supplies on the OID "mbgLtNgSysPsStatus". This
results in field names such as "mbgLtNgSysPsStatus_0" and
"mbgLtNgSysPsStatus_1".

These queries mostly return integers which map to some state. These integers
get decoded into their corresponding string representations and stored in the
OCS Agent Process' session.data object. For more details on this structure, see
the Agent API below. For information about the states corresponding to these
values we refer to the `M1000 manual`_.

.. _M1000 manual: https://www.meinbergglobal.com/download/docs/manuals/english/ltos_6-24.pdf

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Meinberg M1000 Agent we need to add a MeinbergM1000Agent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'MeinbergM1000Agent',
       'instance-id': 'meinberg-m1000',
       'arguments': [['--address', '10.10.10.101'],
                     ['--port', 161],
                     ['--auto-start', True],
                     ['--snmp-version', 3]]},

.. note::
    The ``--address`` argument should be the address of the M1000 on the network.
    This is the main network interface for the device, not the PTP interface,
    which is different.

Docker Compose
``````````````

The Meinberg M1000 Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-m1000:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=meinberg-m1000
      - SITE_HUB=ws://10.10.10.2:8001/ws
      - SITE_HTTP=http://10.10.10.2:8001/call
      - LOGLEVEL=info


The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Agent API
---------

.. autoclass:: socs.agents.meinberg_m1000.agent.MeinbergM1000Agent
    :members:

Supporting APIs
----------------

.. autoclass:: socs.agents.meinberg_m1000.agent.MeinbergSNMP
    :members:
