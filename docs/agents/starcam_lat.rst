.. highlight:: rst

.. _template:

=====================
Star Camera LAT Agent
=====================

# A brief description of the Agent.

.. argparse::
   :module: socs.agents.starcam_lat.agent
   :func: add_agent_args
   :prog: python3 agent.py

Dependencies
------------

# Any external dependencies for agent. Omit if there are none, or they are
# included in the main requirements.txt file.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'StarcamAgent',
       'instance-id': 'starcam-lat',
       'arguments': ['--ip-address', '192.168.1.20',
                     '--port', 8000]},

Docker Compose
``````````````

An example docker compose configuration::

    ocs-starcam-lat:
        image: simonsobs/socs:latest
        hostname: ocs-docker
        network_mode: "host"
        volumes:
          - ${OCS_CONFIG_DIR}:/config
        environment:
          - INSTANCE_ID=starcam-lat
          - LOGLEVEL=info

Description
-----------

# Detailed description of the Agent. Include any details the users or developers
# might find valuable.

Subsection
``````````

# Use subsections where appropriate.

Agent API
---------

.. autoclass:: socs.agents.starcam_lat.agent.StarcamAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.starcam_lat.agent.StarcamHelper
    :members:
    :noindex:
