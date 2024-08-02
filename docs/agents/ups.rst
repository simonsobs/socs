.. highlight:: rst

.. _ups:

====================
UPS Agent
====================

The UPS Agent is an OCS Agent which monitors various UPS models via SNMP.

.. argparse::
    :filename: ../socs/agents/ups/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the UPS Agent we need to add a UPSAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'UPSAgent',
       'instance-id': 'ups',
       'arguments': [['--address', '10.10.10.50'],
                     ['--port', 161],
                     ['--mode', 'acq'],
                     ['--snmp-version', 1],
                     ['--restart-time', 60]]},

.. note::
    The ``--address`` argument should be the address of the UPS on the network.
    The ``--restart-time`` argument should be set to number of minutes before
    exiting the agent. Setting to 0 (default) will not exit the agent.

Docker Compose
``````````````

The UPS Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-ups:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=ups
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info


The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".
If not using HostManager, we must set ``restart: unless-stopped``
to automatically restart the docker container.

Description
-----------

Various UPS models will be used to power various components on the SO site.
The UPS Agent allows the monitoring of a UPS model. It provides information
on the manufacturer and model of the UPS. It monitors the state of each
output, as well as several stats of the battery. The UPS has an Simple Network
Management Protocol (SNMP) interface. The agent has been tested on the
following Falcon models: SSG3K-2T, SSG3KRM-2. These models require a SNMP
interface add-on card to be installed.

The UPS Agent actively issues SNMP GET commands to request the status from
several Object Identifiers (OIDs) specified by the provided Management
Information Base (MIB). We sample only a subset of the OIDs defined by the MIB.
The MIB has been converted from the original .mib format to a .py format that
is consumable via pysnmp and is provided by socs.

Agent Fields
````````````

The fields returned by the Agent are built from the SNMP GET responses from the
UPS. The field names consist of the OID name and the last value of the OID,
which often serves as an index for duplicate pieces of hardware that share a
OID string, i.e. outputs on the OID "upsOutputVoltage". This results in field
names such as "upsOutputVoltage_0" and "upsOutputVoltage_1".

These queries mostly return integers which map to some state. These integers
get decoded into their corresponding string representations and stored in the
OCS Agent Process' session.data object. For more details on this structure, see
the Agent API below. For information about the states corresponding to these
values, refer to the MIB file.

Agent API
---------

.. autoclass:: socs.agents.ups.agent.UPSAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.ups.agent.update_cache
    :members:
    :noindex:
