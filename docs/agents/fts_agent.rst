.. highlight:: rst

.. _fts_aerotech_stage:

==================
FTS Aerotech Agent
==================

This agent is used to communicate with the FTS mirror stage for two FTSs with
Aerotech motion controllers.

.. argparse::
    :filename: ../socs/agents/fts_aerotech/agent.py
    :func: make_parser
    :prog: python3 agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the FTS Agent we need to add a block to our ocs
configuration file. Here is an example configuration block using all of
the available arguments::

      {'agent-class': 'FTSAerotechAgent',
        'instance-id': 'Falcon',
        'arguments': [
          ['--ip-address', '192.168.10.13'],
          ['--port', 8000],
          ['--config_file', 'fts_config.yaml'],
          ['--mode', 'acq'],
          ['--sampling_freqency', 1'],
          ]},


FTS Config
``````````

The FTS takes a separate YAML config file to specify some inner paramters. Here
is an example using all the available arguments.::

    translate: [1, 74.87]
    limits: [-74.8, 74.8]
    speed: 10
    timeout: 10

Agent API
---------

.. autoclass:: socs.agents.fts_aerotech.agent.FTSAerotechAgent
    :members:

Example Clients
---------------

Below is an example client demonstrating full agent functionality.
Note that all tasks can be run even while the data acquisition process
is running.::

    from ocs.ocs_client import OCSClient

    # Initialize the Stages
    fts_agent = OCSClient('Falcon', args=[])
    fts_agent.init.start()
    fts_agent.init.wait()

    # Home Axis
    fts_agent.home.start()
    fts_agent.home.wait()

    # Move to a specific position
    fts_agent.move_to.start( position=0)
    fts_agent.move_to.wait()
