.. highlight:: rst

.. _tektronix3021c:

==================
Tektronix AWG Agent
==================

This agent uses Standard Commands for Programmable Instruments (SCPI)
It works for many function generators, including the Tektronix3021c.
It connects to the function generator over ethernet, and allows
users to set frequency, peak to peak voltage, and turn the AWG on/off.

.. argparse::
    :filename: ../agents/tektronix3021c/tektronix_agent.py
    :func: make_parser
    :prog: python3 tektronix_agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Tektronix AWG Agent we need to add a block to our ocs 
configuration file. Here is an example configuration block using all of 
the available arguments::

      {'agent-class': 'TektronixAWGAgent',
        'instance-id': 'tektronix',
        'arguments': [
          ['--ip-address', '10.10.10.5'],
          ['--gpib-slot', '1']
          ]},

Most function generators (including the Tektronix 3021c) 
have GPIB ports rather than ethernet ports. Therefore a GPIB-to-ethernet
converter is required, and the gpib slot must be specified in the ocs
configuration file. The IP address is then associated with the converter.

Docker
``````
The Tektronix AWG Agent should be configured to run in a Docker container.
An example docker-compose service configuration is shown here::

  ocs-psuK:
    image: simonsobs/ocs-tektronix-agent:latest
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=tektronix"

Example Client
--------------
Below is an example client demonstrating full agent functionality.
Note that all tasks can be run even while the data acquisition process
is running.::

    from ocs.matched_client import MatchedClient
    
    #Initialize the power supply
    tek = MatchedClient('tektronix', args=[])
    tek.init.start()
    tek.init.wait()
    
    #Set AWG frequency
    psuK.set_frequency.start(frequency=200)
    psuK.set_frequency.wait()
    
    #Set AWG peak to peak voltage
    psuK.set_amplitude.start(amplitude=30)
    psuK.set_amplitude.wait()
    
    #Set AWG on/off
    psuK.set_output.start(state=True)
    psuK.set_output.wait()

Agent API
---------

.. autoclass:: agents.tektronix3021c.tektronix_agent.TektronixAWGAgent
    :members: set_frequency, set_amplitude, set_output
