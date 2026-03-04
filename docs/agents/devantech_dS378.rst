.. highlight:: rst

.. _devantech_dS378:

========================
Devantech dS378 Agent
========================

This agent is designed to interface with devantech's dS378 ethernet relay.


.. argparse::
    :filename: ../socs/agents/devantech_dS378/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
`````````````````````

An example site-config-file block::

    {'agent-class': 'dS378Agent',
     'instance-id': 'ds378',
     'arguments': [['--port', 17123],
                   ['--ip_address', '192.168.0.100']]
     },


Docker Compose
``````````````

The dS378 Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-ds378:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=ds378
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
--------------

dS378 is a board with 8 relays that can be cotrolled via ethernet.
The relay can be used for both DC (up to 24 V) and AC (up to 250V).
The electronics box for the stimulator uses this board to control
shutter and powercycling devices such as motor controller or KR260 board.

The driver code assumes the board is configured to communicate with binary codes.
This configuration can be changed via web interface (but requires USB connection as well,
see `documentation <http://www.robot-electronics.co.uk/files/dScriptPublish-4-14.zip>`_ provided from the manufacturer).
You can also configure the ip address and the port number with the same interface.

The device only accepts 10/100BASE communication.

Agent API
---------

.. autoclass:: socs.agents.devantech_dS378.agent.DS378Agent
   :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.devantech_dS378.drivers.DS378
   :members:

.. autoclass:: socs.agents.devantech_dS378.drivers.RelayStatus
   :members:
