.. highlight:: rst

.. _hwp_gripper:

=================
HWP Gripper Agent
=================

Agent which controls and monitor's the HWP's set of three LEY32C-30 linear actuators.
Functions include issuing movement commands, monitoring actuator position, and handling
limit switch activation.

.. argparse::
   :filename: ../socs/agents/hwp_gripper/agent.py
   :func: make_parser
   :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
---------------

An example site-config-file block::

    {'agent-class': 'GripperAgent',
     'instance-id': 'gripper',
     'arguments': [['--mcu_port', '10.10.10.115'],
                   ['--pru_port', 8040],
                   ['--control_port', 8041],
                   ['--return_port', 8042]]},

Docker Compose
--------------

An example docker-compose configuration::

    ocs-hwp-gripper:
        image: simonsobs/socs:latest
        hostname: ocs-docker
        network_mode: "host"
        volumes:
          - ${OCS_CONFIG_DIR}:/config:ro
        command:
          - "--instance-id=gripper"
          - "--site-hub=ws://127.0.0.1:8001/ws"
          - "--site-http=http://127.0.0.1:8001/call"

Agent API
---------

.. autoclass:: socs.agents.hwp_gripper.agent.GripperAgent
   :members:
