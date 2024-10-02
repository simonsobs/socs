.. highlight:: rst

.. _chwp_encoder:

=====================
HWP Encoder BBB Agent
=====================

The optical encoder signals of the CHWP are captured by Beaglebone Black (BBB)
boards with the IRIG-B timing reference.
This agent receives and decodes UDP packets from BBB and publishes the data
feeds.

.. argparse::
    :filename: ../socs/agents/hwp_encoder/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent in a docker container.

OCS Site Config
```````````````

To configure the CHWP encoder BBB agent we need to add a HWPBBBAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA0',
        'arguments': [
          ['--port', '8080'],
          ['--ip', '192.168.11.113'],
          ]}
       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA1',
        'arguments': [
          ['--port', '8081'],
          ['--ip', '192.168.11.114'],
          ]}

This is an example to run two agents because we usually have a couple of
BBBs for A and B phase of the optical encoder for some redundancy.
Multiple BBBs on the same network are distinguished by port numbers.
You should assign a port for each BBB, which should be consistent with
the setting on the BBB side.

Docker Compose
``````````````

The CHWP BBB agent can be run via a Docker container. The following is an
example of what to insert into your institution's docker compose file.
This again is an example to run multiple agents::

  ocs-hwpbbb-agent-HBA0:
    image: simonsobs/socs:latest
    ports:
      - "8080:8080/udp"
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=HBA0
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

  ocs-hwpbbb-agent-HBA1:
    image: simonsobs/socs:latest
    ports:
      - "8081:8081/udp"
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=HBA1
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

Description
-----------

session.data
````````````
The most recent data collected is stored in session.data in the following structure.
The approx_hwp_freq is initialized by -1 and will be updated by non-negative rotation frequency
if encoder agent is receiving encoder signal.
If chwp is completely stopped, approx_hwp_freq will not be updated.::

    >>> response.session['data']
    {'approx_hwp_freq':      2.0,
     'encoder_last_updated': 1659486962.3731978,
     'irig_time':            1659486983,
     'irig_last_updated':    1659486983.8985631}

Agent API
---------

.. autoclass:: socs.agents.hwp_encoder.agent.HWPBBBAgent
    :members:
