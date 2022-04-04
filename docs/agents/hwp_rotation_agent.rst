.. highlight:: rst

.. _hwp_rotation_agent:

==================
HWP Rotation Agent
==================

.. argparse::
    :filename: ../agents/hwp_rotation/rotation_agent.py
    :func: make_parser
    :prog: python3 rotation_agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

An example site-config-file block::

      {'agent-class': 'RotationAgent',
       'instance-id': 'rotator',
       'arguments': [['--kikusui-ip', '10.10.10.100'],
                     ['--kikusui-port', '2000'],
                     ['--pid-ip', '10.10.10.101'],
                     ['--pid-port', '2001']]},

Docker Compose
``````````````

An example docker-compose configuration::

  ocs-hwp-rotation:
    image: simonsobs/ocs-hwp-rotation-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=hwp-rotation"
      - "--site-hub=ws://127.0.0.1:8001/ws"
      - "--site-http=http://127.0.0.1:8001/call"

.. note::
    Since the Agent container needs ``network_mode: "host"``, it must be
    configured to connect to the crossbar server as if it was on the host
    system. In this example the crossbar server is running on localhost,
    ``127.0.0.1``, but on your network this may be different.

Description
-----------


Agent API
---------

.. autoclass:: agents.hwp_rotation.rotation_agent.RotationAgent
    :members:

Supporting APIs
---------------

.. automodule:: socs.agent.pmx
    :members:
    :noindex:
