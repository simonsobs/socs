.. highlight:: rst

.. _hwp_gripper:

=================
HWP Gripper Agent
=================

Agent which controls and monitor's the HWP's set of three LEY32C-30 linear actuators.

.. argparse::
   :filename: ../socs/agents/hwp_gripper/agent.py
   :func: make_parser
   :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
`````````````````````

An example site-config-file block::

    {'agent-class': 'HWPGripperAgent',
     'instance-id': 'hwp-gripper',
     'arguments': [ '--mcu_ip', '10.10.10.115',
                    '--control_port', 8041,
                    '--warm-grip-distance, 9.2, 10.6, 9.8,
                    '--adjustment-distance, 0., 0., 0.,
                    '--supervisor-id', 'hwp-supervisor',
                    '--no-data-warn-time', 60,
                    '--no-data-shutdown-time', 300,  # 5 minutes
                  ]
     },

Docker Compose
`````````````````````

An example docker-compose configuration::

    ocs-hwp-gripper:
        image: simonsobs/socs:latest
        hostname: ocs-docker
        network_mode: "host"
        volumes:
          - ${OCS_CONFIG_DIR}:/config:ro
        environment:
          - INSTANCE_ID=hwp-gripper

Description
--------------
This agent communicates with the `gripper server in sobonelib <sobonelib_>`_, and has operations
to move actuators, home actuators, check if they are in-position, etc.

.. _sobonelib: https://github.com/simonsobs/sobonelib/tree/main/hwp_gripper/control

This agent has two long-running processes, one to regularly query the gripper
server for the gripper-state, and the other to regularly check the hwp-supervisor for the
overall HWP state.

Shutdown mode
```````````````

If there is something wrong with the HWP, due to power or network outages, or cryogenic issues,
it is no longer safe to operate the gripper, as we may not have an accurate understanding of
whether or not the HWP is spinning. If the hwp-supervisor issues a shutdown signal, or if
a sufficiently long time passes where the agent is unable to connect to the supervisor,
the agent enters a shutdown mode in which potentially dangerous operations are blocked.

Shutdown-mode can be cancelled by manually restarting the agent, or by running
the ``cancel_shutdown`` task, which will allow you to operate the grippers.


Agent API
---------

.. autoclass:: socs.agents.hwp_gripper.agent.HWPGripperAgent
   :members:
