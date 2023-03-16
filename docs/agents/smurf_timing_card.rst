.. highlight:: rst

.. _smurf_timing_card:

========================
Smurf Timing Card Agent
========================
The Smurf Timing Card Agent monitors several diagnostic EPICS registers from SLAC's
timing software.

.. argparse::
    :filename: ../socs/agents/smurf_timing_card/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
------------------------------
Below are configuration examples for the ocs config file and for the
docker-compose service.

OCS Site Config
`````````````````
Below is an example of an agent configuration block for the ocs-site-config
file::

    {'agent-class': 'SmurfTimingCardAgent',
     'instance-id': 'smurf-timing-card',
     'arguments': [
        '--timeout', 3,
        '--sleep-time', 30,
        # '--use-monitor',
     ]},

Note the ``--use-monitor`` argument is commented out because this should be
False by default.

Docker Compose
````````````````
Below is an example of the docker-compose service for the timing card agent::

    ocs-smurf-timing-card:
        image: simonsobs/socs:latest
        <<: *log-options
        network_mode: host
        hostname: ocs-docker
        container_name: ocs-smurf-timing-card
        volumes:
            - ${OCS_CONFIG_DIR}:/config
        environment:
            - EPICS_CA_ADDR_LIST=127.255.255.255
            - EPICS_CA_MAX_ARRAY_BYTES=80000000
            - INSTANCE_ID=smurf-timing-card

Description
--------------

This agent uses EPICS to monitor several diagnostic registers of the SMuRF
timing card software. More detail on the TPG PVs can be found `here`_ if
you have access to the SLAC confluence.

.. _here: https://confluence.slac.stanford.edu/display/~khkim/PV+List+for+TPG+ioc

Descriptions for the PVs monitored here (pulled directly from the SLAC
confluence page) are:

.. list-table::
    :header-rows: 1

    * - PV
      - Description
    * - TPG:SMRF:1:COUNTPLL
      - PLL Change Counter
    * - TPG:SMRF:1:COUNT186M
      - 186 MHz counter
    * - TPG:SMRF:1:COUNTSYNCERR
      - Sync Error Counter
    * - TPG:SMRF:1:COUNTINTV
      - Interval Counter
    * - TPG:SMRF:1:COUNTBRT
      - Base Rate Trigger Counter
    * - TPG:SMRF:1:COUNTTXCLK
      - Tx Clock Counter
    * - TPG:SMRF:1:DELTATXCLK
      - Delta Tx Clock
    * - TPG:SMRF:1:RATETXCLK
      - TX Clock Rate

Agent API
-----------
.. autoclass:: socs.agents.smurf_timing_card.agent.SmurfTimingCardAgent
    :members:
