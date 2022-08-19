.. highlight:: rst

.. _hwp_supervisor:

====================
HWP Supervisor Agent
====================

The HWP Supervisor Agent monitors the temperature of a configured 40K
thermometer channel from a Lakeshore 240 Agent as well as the UPS battery state
from a UPS Agent. If conditions have degraded from their optimal operating
state, the supervisor will broadcast a warning and shutdown the HWP safely.

.. argparse::
    :filename: ../agents/hwp_supervisor/hwp_supervisor.py
    :func: make_parser
    :prog: python3 hwp_supervisor.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure the HWP Supervisor for use with OCS you need to add a
HwpSupervisorAgent block to your ocs configuration file. Here is an example
configuration block::

      {'agent-class': 'HwpSupervisorAgent',
       'instance-id': 'hwp-supervisor',
       'arguments': ['--mode', 'monitor',
                     '--config', 'hwp_supervisor.yaml']},

HWP Supervisor Config
`````````````````````

A HWP Supervisor configuration file allows the user to define which Lakeshore
240 temperature channel and which UPS to monitor, as well as which agent
instance-id's correspond to the HWP control Agents for shutdown. Here is an
example configuration file:

.. code-block:: yaml

    lakeshore-device:
        instance-id: "lakeshore-240-1"
        field: "Channel_1"
        valid-range: (0, 60)
    ups-device:
        instance-id: "ups-1"
        field: "battery_remaining"
        valid-range: (90, 100)
    hwp-rotation-agent:
        instance-id: "rotation-agent1"
    hwp-gripper-agent:
        instance-id: "gripper-agent1"
    hwp-encoder-agent:
        instance-id: "encoder-agent1"

Docker Compose
``````````````

The Lakeshore 372 Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-hwp-supervisor:
    image: simonsobs/ocs-hwp-supervisor-agent:latest
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=hwp-supervisor"

Description
-----------

More documentation on how to use this should go here.

Agent API
---------

.. autoclass:: agents.hwp_supervisor.hwp_supervisor.HwpSupervisorAgent
    :members:
