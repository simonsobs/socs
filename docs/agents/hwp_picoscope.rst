.. highlight:: rst

.. _hwp_picoscope:

======================
HWP Picoscope Agent
======================

The HWP picoscope agent interfaces with Picoscope 3403D MSO to operate the LC sensors which remotely measures the 3 dimentional position and temperature of hwp.
This agent biases the LC sensors and measures the 4 channels of analog input and 8 channels of digital input.

.. argparse::
    :filename: ../agents/hwp_picoscope/pico_agent.py
    :func: make_parser
    :prog: python3 pico_agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for 
running the agent in a docker container.

ocs-config
``````````
To configure the HWP picoscope agent we need to add a HWPPicoscopeAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'HWPPicoscopeAgent',
        'instance-id': 'picoscope',
        'arguments': []}

Docker
``````
The HWP picoscope agent can be run via a Docker container. The following is an 
example of what to insert into your institution's docker-compose file.
Currently this agent is confirmed to work by privileded true, but this needs to be improved.
::

  picoscope:
    image: simonsobs/ocs-hwp-picoscope-agent:latest
    hostname: ocs-docker
    privileged: true 
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /dev:/dev
    command:
      - "--instance-id=picoscope"
      - "--site-hub=ws://crossbar:8001/ws"
      - "--site-http=http://crossbar:8001/call"
