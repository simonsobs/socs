.. highlight:: rst

.. _chwp_encoder:

======================
CHWP Encoder BBB Agent
======================

The optical encoder signals of the CHWP are captured by Beaglebone Black (BBB)
boards with the IRIG-B timing reference.
This agent receives and decodes UDP packets from BBB and publishes the data
feeds.

.. argparse::
    :filename: ../agents/chwp/hwpbbb_agent.py
    :func: make_parser
    :prog: python3 hwpbbb_agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for 
running the agent in a docker container.

ocs-config
``````````
To configure the CHWP encoder BBB agent we need to add a HWPBBBAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA0',
        'arguments': [
          ['--port', '8080'],
          ]}
       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA1',
        'arguments': [
          ['--port', '8081'],
          ]}

This is an example to run two agents because we usually have a couple of
BBBs for A and B phase of the optical encoder for some redundancy.
Multiple BBBs on the same network are distinguished by port numbers.
You should assign a port for each BBB, which should be consistent with
the setting on the BBB side.

Docker
``````
The CHWP BBB agent can be run via a Docker container. The following is an 
example of what to insert into your institution's docker-compose file.
This again is an example to run multiple agents::

  ocs-hwpbbb-agent-HBA0:
    image: simonsobs/ocs-hwpbb-agent:latest
    ports:
      - "8080:8080/udp"
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=HBA0"
      - "--site-hub=ws://crossbar:8001/ws"
      - "--site-http=http://crossbar:8001/call"

  ocs-hwpbbb-agent-HBA1:
    image: simonsobs/ocs-hwpbb-agent:latest
    ports:
      - "8081:8081/udp"
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=HBA1"
      - "--site-hub=ws://crossbar:8001/ws"
      - "--site-http=http://crossbar:8001/call"


