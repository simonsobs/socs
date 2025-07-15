.. highlight:: rst

.. _srs_cg635:

====================
SRS CG635 Agent
====================

The SRS CG635 Agent is an OCS Agent which retrieves data from the SRS CG635 clock
via a Prologix GPIB interface.

.. argparse::
    :filename: ../socs/agents/srs_cg635/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
---------------

To configure the SRS CG635 Agent we need to add an SRSCG635Agent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'SRSCG635Agent',
       'instance-id': 'srs-cg635',
       'arguments': [['--ip-address', '10.10.10.10'],
                     ['--gpib-slot', 23],
                     ['--mode', 'acq']]},

.. note::
    The ``--ip-address`` argument should be the IP address of the Prologix GPIB interface.
    The ``--gpib-slot`` argument should be the GPIB address set on the SRS CG635.
    For first time setup, use the utility software available on the `Prologix website`_.
    The ``NetFinder`` utility should be used to find the IP address of the Prologix GPIB interface.
    The ``Prologix GPIB Interface`` utility should be used to set the GPIB address.

.. _Prologix website: https://prologix.biz/resources/

Docker Compose
--------------

The SRS CG635 Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-srs-cg635:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=srs-cg635
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

The SRS CG635 Agent retrieves data from the SRS CG635 clock via a Prologix
GPIB interface. The SRS CG635 drivers are used to connect to the Prologix
GPIB interface.

Agent API
---------

.. autoclass:: socs.agents.srs_cg635.agent.SRSCG635Agent
    :members:

Supporting APIs
---------------

.. automodule:: socs.agents.srs_cg635.drivers
    :members:
    :undoc-members:
    :show-inheritance:
