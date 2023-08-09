.. highlight:: rst

.. _hwp_supervisor:

=====================
HWP Supervisor Agent
=====================

The HWP supervisor agent monitors and can issue commands to hwp subsystems,
and monitors data from other agents on the network that may be relevant to HWP
operation.  Session data from the supervisor agent's ``monitor`` task can be
used to trigger shutdown procedures in the HWP subsystems.


.. argparse::
    :filename: ../socs/agents/hwp_supervisor/agent.py
    :func: make_parser
    :prog: python3 agent.py


Configuration File Examples
---------------------------

OCS Site Config
````````````````````

Here is an example of a config block you can add to your ocs site-config file::

       {'agent-class': 'HWPSupervisor',
        'instance-id': 'hwp-supervisor',
        'arguments': [
            '--sleep-time', 5,
            '--hwp-lakeshore-id', 'LS240_test',
            '--hwp-temp-field', 'Channel_06',
            '--hwp-temp-thresh', 70,  # Kelvin
            '--hwp-encoder-id', 'HBA0',
            '--hwp-rotation-id', 'rotator',
            '--hwp-ups-id', 'ups'
        ]}


Docker Compose
````````````````

If you want to run this agent in a docker, you can use a configuration like the
one below::

  ocs-hwp-supervisor:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=hwp-supervisor
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Description
--------------

This agent has two main purposes:

- Monitor HWP subsystems and related agents to make high level determinations
  such as when subsystems should start their shutdown procedure
- Serve as a host for high-level HWP operations that require coordinated control
  of various HWP subsystems, such as "Begin rotating at 2 Hz"

Right now only the first point is implemented, but operations can be added here
as we need them.

HWP subsystems should implement a ``monitor_shutdown`` process that uses the
``get_op_data`` function to get the hwp-supervisor's session data, and check
the ``action`` field to determine if shutdown should be initiated.


Agent API
-----------

.. autoclass:: socs.agents.hwp_supervisor.agent.HWPSupervisor
    :members:

.. autoclass:: socs.agents.hwp_supervisor.agent.get_op_data
