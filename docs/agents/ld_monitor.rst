.. highlight:: rst

========================
Lightning Detector Agent
========================

The lightning detector agent communicates with the Lightning Detector System at
the site and parses the data to obtain approximate lightning strike distances
and standardized alarm levels.

.. argparse::
   :module: socs.agents.ld_monitor.agent
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
     'instance-id': 'ld-monitor',
     'arguments': ['--mode', 'acq']},

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-ld-monitor:
        image: simonsobs/socs:latest
        hostname: ocs-docker
        ports:
          - "1110:1110/udp"
        environment:
          - INSTANCE_ID=ld-monitor
          - SITE_HUB=ws://127.0.0.1:8001/ws
          - SITE_HTTP=http://127.0.0.1:8001/call
          - LOGLEVEL=info
        volumes:
          - ${OCS_CONFIG_DIR}:/config

Description
-----------

The Lightning Detector System is connnected through serial communication with a
dedicated PC at the site, in which a propietary application calculates
approximate lightning strike distances and adjusts alarm levels accordingly.
Data is parsed and the most important parameters are updated. The dedicated PC
is continously running a script that streams the data via UDP to the client.

Transmitted Data
````````````````

The lightning detector transmits its data in "sentences". There are 5 types of
expected sentences:

* electric field
* lightning strike
* high-field
* status
* alarm timers

Electric field sentences report the electric field value measured by the
Electric Field Mill in kV/m. Strike sentences include lightning strike distance
and units (meters or miles) and is only transmitted if a strike is detected.
High field sentences report an alarm status with respect to set thresholds of
electric field. Status sentences include data such as alarms (red, orange,
yellow), remaining timers, all clear status, fault codes, among others. Alarm
timers sentences are disregarded, as its information is redundant. Each of the
sentences' data are parsed and published to the feed.

Agent API
---------

.. autoclass:: socs.agents.ld_monitor.agent.LDMonitorAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.ld_monitor.agent.LDMonitor
    :members:
