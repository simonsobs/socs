.. highlight:: rst

.. _labjack:

=============
LabJack Agent
=============

LabJacks are generic devices for interfacing with different sensors, providing
analog and digital inputs and outputs. They are then commanded and queried over
ethernet.

.. argparse::
    :filename: ../agents/labjack/labjack_agent.py
    :func: make_parser
    :prog: python3 labjack_agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the LabJack Agent we need to add a LabJackAgent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

        {'agent-class': 'LabJackAgent',
         'instance-id': 'labjack',
         'arguments':[
           ['--ip-address', '10.10.10.150'],
           ['--num-channels', '13'],
           ['--functions', '{
           "Channel 1": ["1.3332*10**(2*v - 11)", "mBar"],
           "Channel 2": ["2*10**(v - 5)", "mBar"]
           }'], 
           ['--mode', 'acq'],
           ]},

You should assign your LabJack a static IP, you'll need to know that here. 
The 'functions' argument is a dictionary that specifies functions and units
to apply to the output voltages of certain channels. In this example 
channels 1 and 2 will record pressure data by applying functions to the 
voltage output 'v' of their respective channels. This data is published to 
the feed in the same manner as the voltages. 

Docker
``````
The LabJack Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-labjack:
    image: simonsobs/ocs-labjack-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    command:
      - "--instance-id=labjack"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Example Client
--------------
Since labjack functionality is currently limited to acquiring data, which can 
enabled on startup, users are likely to rarely need a client. This example
shows the basic acquisition funcionality::

    #Initialize the labjack
    from ocs import matched_client
    lj = matched_client.MatchedClient('labjack', args=[])
    lj.init_labjack.start()
    lj.init_labjack.wait()

    #Start data acquisiton
    status, msg, session = lj.acq.start()
    print(session)

    #Get the current data values 1 second after starting acquistion
    time.sleep(1)
    status, message, session = lj.acq.status()
    print(session["data"])

    #Stop acqusition
    lj.acq.stop()
    lj.acq.wait()


Agent API
---------

.. autoclass:: agents.labjack.labjack_agent.LabJackAgent
    :members: init_labjack_task, start_acq
