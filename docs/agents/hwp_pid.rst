.. highlight:: rst

.. _hwp_pid:

=============
HWP PID Agent
=============

.. argparse::
    :filename: ../socs/agents/hwp_pid/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

An example site-config-file block::

      {'agent-class': 'HWPPIDAgent',
       'instance-id': 'hwp-pid',
       'arguments': [['--ip', '10.10.10.101'],
                     ['--port', '2000'],
                     ['--mode', 'acq']]},

Docker Compose
``````````````

An example docker-compose configuration::

  ocs-hwp-pid:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=hwp-pid
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

.. note::
    Since the Agent container needs ``network_mode: "host"``, it must be
    configured to connect to the crossbar server as if it was on the host
    system. In this example the crossbar server is running on localhost,
    ``127.0.0.1``, but on your network this may be different.

Agent API
---------

.. autoclass:: socs.agents.hwp_pid.agent.HWPPIDAgent
    :members:
