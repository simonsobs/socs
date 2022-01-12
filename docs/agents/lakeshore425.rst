.. highlight:: rst

.. _lakeshore425:

======================
Lakeshore 425
======================

The Lakeshore Model 425 gaussmeter is a device which measure the magnetic field by hall sensor. 
This agent is used to measure the magnetic field from the superconducting magnetic bearing of the CHWP rotation mechanism and to monitoring the status of floating and rotating CHWP.

.. argparse::
    :filename: ../agents/lakeshore425/LS425_agent.py
    :func: make_parser
    :prog: python3 LS425_agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for 
running the agent in a docker container.

OCS Site Config
```````````````
To configure the ocs-lakeshore425-agent we need to add a Lakeshore425Agent 
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'Lakeshore425Agent',
       'instance-id': 'LS425',
       'arguments': [
         ['--port', '/dev/LS425'],
         ['--mode', 'acq'],
         ['--sampling-frequency', 1.],
       ]},

If you would like to chanege the setting or check the status of the lakeshore 425, the ``--mode`` argument should be ``'init'``.

Docker Compose
``````````````
The ocs-lakeshore425-agent can be run via a Docker container. The following is an 
example of what to insert into your institution's docker-compose file.::

  ocs-lakeshore425-agent:
    image: simonsobs/ocs-lakeshore425-agent:latest
    device:
      - /dev/LS425:/dev/LS425
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=LS425"
      - "--site-hub=ws://crossbar:8001/ws"
      - "--site-http=http://crossbar:8001/call"

Agent API
---------

.. autoclass:: agents.lakeshore425.LS425_agent.LS425Agent
    :members:
