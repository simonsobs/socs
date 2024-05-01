.. highlight:: rst

========================
Lightning Detector Agent
========================

The lightning detector agent communicates with the Lightning Detector System at the site and parses the data to obtain approximate lightning strike distances and standardized alarm levels.

.. argparse::
   :module: socs.agents.ld_monitor.agent.LDMonitorAgent
   :func: make_parser
   :prog: agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'LDMonitorAgent',
       'instance-id': 'ld_monitor',
       'arguments': [['--mode', 'acq']},

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-template:
        image: simonsobs/ocs-lightning-detector:latest
        hostname: ocs-docker
        environment:
          - LOGLEVEL=info
        volumes:
          - ${OCS_CONFIG_DIR}:/config

Description
-----------

The Lightning Detector System is connnected through serial communication with a dedicated PC at the site, in which a propietary application calculates approximate lightning strike distances and adjusts alarm levels accordingly. Data is parsed and the most important parameters are updated. The dedicated PC is continously running a script that streams the data via UDP to the client.

Transmitted data
----------------

The lightning detector transmits its data in "sentences". There are 5 types of expected sentences: 
-electric field
-lightning strike
-high-field
-status
-alarm timers
Electric field sentences report the electric field value measured by the Electric Field Mill in kV/m. Strike sentences include lightning strike distance and units (meters or miles) and is only transmitted if a strike is detected. High field sentences report an alarm status with respect to set thresholds of electric field. Status sentences include data such as alarms (red, orange, yellow), remaining timers, all clear status, fault codes, among others. Alarm timers sentences are disregarded, as its information is redundant. Each of the sentences' data is parsed and data updated to the feed.

Agent API
---------

.. autoclass:: socs.agents.ld_monitor.agent.LDMonitorAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.ld_monitor.agent.LDMonitor
    :members:
