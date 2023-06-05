.. highlight:: rst

.. _generator:

====================
Generator Agent
====================

The Generator Agent is an OCS Agent which monitors on-site generators via Modbus.

.. argparse::
    :filename: ../socs/agents/generator/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Generator Agent we need to add a GeneratorAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'GeneratorAgent',
       'instance-id': 'generator',
       'arguments': [['--host', '192.168.2.88'],
                     ['--port', 502],
                     ['--mode', 'acq'],
                     ['--read-config', '/home/ocs/CONFIG/ocs/generator-config.yaml']]}

.. note::
    The ``--host`` argument should be the IP address of the generator on the network.

Docker Compose
``````````````

The Generator Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-generator:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=generator
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info


The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

On-site generators will be used to provide power to the SO site.
Each generator have the same controller/interface, the Deep Sea Electronics (DSE)
8610 mark II. The Generator Agent allows the monitoring of each generator controller
via Modbus. It queries registers and publishes data in an acquisition process. The
agent has been tested with on-site generators.

The Generator Agent requires a config file which contains information on all
possible registers that it may query from the generator controller. The config file
also sets the amount of registers we want to query in the acquisition process.

Agent Fields
````````````

The fields consist of the register name and the last value, which are necessarily
formatted depending on the register.

Agent API
---------

.. autoclass:: socs.agents.generator.agent.GeneratorAgent
    :members:
