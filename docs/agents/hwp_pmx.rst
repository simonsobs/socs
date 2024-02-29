.. highlight:: rst

.. _hwp_pmx:

=============
HWP PMX Agent
=============

.. argparse::
    :filename: ../socs/agents/hwp_pmx/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

An example site-config-file block::

      {'agent-class': 'HWPPMXAgent',
       'instance-id': 'hwp-pmx',
       'arguments': [['--ip', '10.10.10.100'],
                     ['--port', '5025'],
                     ['--sampling-frequency', 1],
                     ['--supervisor-id', 'hwp-supervisor']]},

Docker Compose
``````````````

An example docker-compose configuration::

  ocs-hwp-pmx:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=hwp-pmx
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

.. note::
    Since the Agent container needs ``network_mode: "host"``, it must be
    configured to connect to the crossbar server as if it was on the host
    system. In this example the crossbar server is running on localhost,
    ``127.0.0.1``, but on your network this may be different.

Description
-----------

The HWP PMX Agent interfaces with the PMX Kikusui power supply and allows
control of the current and voltage that drives the CHWP rotation. The PMX
provides several connection options for communicating remotely with the
hardware. For the HWP PMX Agent we have written the interface for
communication via Ethernet cable.

Protection Mode
````````````````
The PMX enters protection mode and stops outputting when something harmful
occurs. The HWP PMX Agent monitors the state of the protection mode and
outputs a protection code and message to ``prot_code`` and ``prot_msg`` for
each data acquisition. There are several possible situations that can cause
entering the protection mode. Below is a table showing the protection codes
and corresponding situations.

+--------------+--------------------------------------------+
| prot_code    | Description                                |
+==============+============================================+
| 0            | not in protection mode                     |
+--------------+--------------------------------------------+
| 1            | overcurrent protection                     |
+--------------+--------------------------------------------+
| 2            | overvoltage protection                     |
+--------------+--------------------------------------------+
| 3            | AC power failure or power interuption      |
+--------------+--------------------------------------------+
| 5            | over temperature protection                |
+--------------+--------------------------------------------+
| 7            | IOC communication error                    |
+--------------+--------------------------------------------+

When the PMX enters the protection mode, the cause must be removed and the
protection mode must be deactivated in order to resume output. After removing
the cause of the protection, output can be resumed by executing the following
API tasks via the HWP PMX Agent::

    pmx.clear_alarm()
    pmx.set_on()

Agent API
---------

.. autoclass:: socs.agents.hwp_pmx.agent.HWPPMXAgent
    :members:
