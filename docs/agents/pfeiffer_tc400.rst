.. highlight:: rst

.. _pfeiffer_tc400_agent:

==============
Pfeiffer TC400
==============

The Pfeiffer TC400 agent is an OCS Agent which controls the 
Pfeiffer TC400 electronic drive unit, which control the turbos used 
for the bluefors DR. The communcation is done over serial, and should be 
integrated into OCS using a serial-to-ethernet converter.

.. argparse::
    :filename: ../agents/pfeiffer_tc400/pfeiffer_tc400_agent.py
    :func: make_parser
    :prog: python3 pfeiffer_tc400_agent.py

Description
-----------

Serial Configuration
````````````````````
::

    baudrate=9600
    data bits=8
    stop bits=1
    parity=None
    Flow control=RTS/CTS
    FIFO=Enable
    Interface=RS-485-2-Wire

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````
To configure the Pfeiffer TC400 Agent we need to add a PfeifferTC400Agent
block to our ocs configuration file. The IP address and port 
number are from the serial-to-ethernet converter. The turbo address is 
visible on the power supply front panel. Here is an example configuration 
block using all of the available arguments::

 {'agent-class': 'PfeifferTC400Agent',
  'instance-id': 'pfeifferturboA',
  'arguments': [['--ip-address', '10.10.10.129'],
                ['--port-number', '4002'],
                ['--turbo-address', '1']]},


Docker Compose
``````````````
The agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-pfeiffer-turboA:
    image: simonsobs/ocs-pfeiffer-tc400-agent
    <<: *log-options
    hostname: manny-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    command:
      - "--instance-id=pfeifferturboA"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Agent API
---------

.. autoclass:: agents.pfeiffer_tc400.pfeiffer_tc400_agent.PfeifferTC400Agent
    :members:

Example Clients
---------------
The turbo agent can start and stop a turbo, acknowledge an error (this is
required to start again after an error occurs), and acquire turbo data. This
example client shows all of this functionality::

    from ocs.ocs_client import OCSClient
    client = OCSClient("pfeifferturboA)
    
    # Start data acq
    status, message, session = client.acq.start()
    print(session)
    
    # Stop data acq
    client.acq.stop()
    client.acq.wait()

    # Start the turbo
    client.turn_turbo_on()

    # Stop the turbo
    client.turn_turbo_off()
    
    # Acknowledge errors
    client.acknowledge_turbo_errors()

Driver API
----------

.. autoclass:: agents.pfeiffer_tc400.pfeiffer_tc400_driver.PfeifferTC400
    :members:
