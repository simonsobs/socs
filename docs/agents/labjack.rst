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
           ['--mode', 'acq'],
           ]},

You should assign your LabJack a static IP, you'll need to know that here.

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

Agent API
---------

.. autoclass:: agents.labjack.labjack_agent.LabJackAgent
    :members: init_labjack_task, start_acq
