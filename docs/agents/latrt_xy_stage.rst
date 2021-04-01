.. highlight:: rst

.. _latrt_xy_stage:

=====================
LATRt XY Stage Agent
=====================

This agent is used to communicate with the XY Stages used in the LATRt lab.
These stages are run off a Raspberry Pi connected to some custom electronics
boards for communicating with the stages. 

Since control of these stages need to be accessible inside and outside OCS,
their drivers are shared `here
<https://github.com/kmharrington/xy_stage_control>`_. 

.. argparse::
    :filename: ../agents/xy_stage/xy_latrt_agent.py
    :func: make_parser
    :prog: python3 xy_latrt_agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the LATRt XY Stage Agent we need to add a block to our ocs 
configuration file. Here is an example configuration block using all of 
the available arguments::

      {'agent-class': 'LATRt_XY_StageAgent',
        'instance-id': 'XYWing',
        'arguments': [
          ['--ip-address', '192.168.10.15'],
          ['--port', 3010],
          ['--mode', 'acq'],
          ['--sampling_freqency', 2'],
          ]},

Example Client
--------------
Below is an example client demonstrating full agent functionality.
Note that all tasks can be run even while the data acquisition process
is running.::

    from ocs.matched_client import MatchedClient
    
    #Initialize the Stages
    xy_agent = MatchedClient('XYWing', args=[])
    xy_agent.init.start()
    xy_agent.init.wait()
    
    #Move in X 
    xy_agent.move_x_cm.start( distance=6, velocity=1)
    xy_agent.move_x_cm.wait()
    
    #Move in Y
    xy_agent.move_y_cm.start( distance=6, velocity=1)
    xy_agent.move_y_cm.wait()
    
    #Get instantaneous position
    status, message, session = xy_stage.acq.status()
    print(session['data']['data'])
    
Agent API
---------

.. autoclass:: agents.xy_stage.xy_latrt_agent.LATRt_XY_Agent
    :members: init_xy_stage_task, move_x_cm, move_y_cm, set_position, start_acq, stop_acq 
