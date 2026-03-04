.. highlight:: rst

.. _kikusui_pcr500ma:

========================
KIKUSUI PCR500MA Agent
========================

This agent is designed to interface with KIKUSUI's PCR500MA AC power supply.


.. argparse::
    :filename: ../socs/agents/kikusui_pcr500ma/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
`````````````````````

An example site-config-file block::

    {'agent-class': 'PCR500MAAgent',
     'instance-id': 'pcr500ma',
     'arguments': [['--port', 5025],
                   ['--ip-address', '192.168.0.100']]
     },


Docker Compose
``````````````

The PCR Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-pcr500ma:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=pcr500ma
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
--------------

PCR500MA is an AC power supply that can be cotrolled via ethernet.
This power supply will be used to the stimulator heater to raise its temperature.

The device only accepts 10/100BASE communication.
Manual can be found `here <https://manual.kikusui.co.jp/P/PCR_MA_USER_E4.pdf>`_.


Agent API
---------

.. autoclass:: socs.agents.kikusui_pcr500ma.agent.PCR500MAAgent
   :members:
Supporting APIs
---------------

.. autoclass:: socs.agents.kikusui_pcr500ma.drivers.PCR500MA
   :members:

.. autoclass:: socs.agents.kikusui_pcr500ma.drivers.PCRCoupling
   :members:
