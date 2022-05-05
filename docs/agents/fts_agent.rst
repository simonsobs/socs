.. highlight:: rst

.. _fts_aerotech_stage:

=====================
FTS Aerotech Agent
=====================

This agent is used to communicate with the FTS mirror stage for two FTSs with
Aerotech motion controllers. 

.. argparse::
    :filename: ../agents/fts_aerotech_stage/fts_aerotech_agent.py
    :func: make_parser
    :prog: python3 fts_aerotech_agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the FTS Agent we need to add a block to our ocs 
configuration file. Here is an example configuration block using all of 
the available arguments::

      {'agent-class': 'FTSAerotechAgent',
        'instance-id': 'Falcon',
        'arguments': [
          ['--ip-address', '192.168.10.13'],
          ['--port', 8000],
          ['--mode', 'acq'],
          ['--sampling_freqency', 1'],
          ]},

Example Client
--------------
Below is an example client demonstrating full agent functionality.
Note that all tasks can be run even while the data acquisition process
is running.::

    from ocs.matched_client import MatchedClient
    
    #Initialize the Stages
    fts_agent = MatchedClient('Falcon', args=[])
    fts_agent.init.start()
    fts_agent.init.wait()
    
    #Home Axis 
    fts_agent.home.start()
    fts_agent.home.wait()
    
    #Move to a specific position
    fts_agent.move_to.start( position=0)
    fts_agent.move_to.wait()
    
    
Agent API
---------

.. autoclass:: agents.fts_aerotech_stage.fts_aerotech_agent.FTSAerotechAgent
    :members: init_stage_task, home_task, move_to, start_acq, stop_acq 
