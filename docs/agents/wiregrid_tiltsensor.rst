.. highlight:: rst

.. _wiregrid_tiltsensor:

==========================
Wiregrid Tilt Sensor Agent
==========================

# Enter a brief description here.

.. argparse::
   :filename: ../socs/agents/wiregrid_tiltsensor/agent.py
   :func: make_parser
   :prog: python3 agent.py

Dependencies
------------

# List if any, else remove section.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WiregridTiltSensorAgent',
     'instance-id': 'wg-tilt-sensor',
     'arguments': ['--ip-address', '10.10.10.73']},

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-wg-tilt-sensor:
        image: simonsobs/socs:latest
        hostname: ocs-docker
        network_mode: "host"
        environment:
          - INSTANCE_ID=wg-tilt-sensor
        volumes:
          - ${OCS_CONFIG_DIR}:/config:ro

- Since the agent within the container needs to communicate with hardware on the
  host network you must use ``network_mode: "host"`` in your compose file.

Description
-----------

# Longer description here if needed.

Agent API
---------

.. autoclass:: socs.agents.wiregrid_tiltsensor.agent.WiregridTiltsensorAgent
    :members:
