.. highlight:: rst

.. _wiregrid_encoder:

=======================
Wiregrid Encoder Agent
=======================

The Wiregrid Encoder Agent records the wire-grid encoder outputs
related to the rotational angle of the wire-grid.
The encoder reader data is read by a BeagleBoneBlack
on the grid-loader electronics plate.
The BeagleBoneBlack sends the measured data to this agent
via ethernet UDP connection.
This agent parses the received data to a readable data and records it.

.. argparse::
   :filename: ../socs/agents/wiregrid_encoder/agent.py
   :func: make_parser
   :prog: python3 agent.py

Dependencies
------------

This agent recieves the data from BeagleBoneBlack.
Therefore, a script reading the encoder data
should be running in the BeagleBoneBlack:
https://github.com/simonsobs/wire_grid_loader/tree/master/Encoder/Beaglebone.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WiregridEncoderAgent',
     'instance-id': 'wgencoder',
     'arguments': [['--port', 50007]]},

The port is used to receive the data from the BeagleBoneBlack.
The port number is determined in the script running in the BeagleBoneBlack.

Docker Compose
``````````````

An example docker compose configuration::

    ocs-wgencoder-agent:
      image: simonsobs/socs:latest
      restart: always
      hostname: ocs-docker
      environment:
        - INSTANCE_ID=wgencoder
      volumes:
        - ${OCS_CONFIG_DIR}:/config:ro
        - "/data/wg-data:/data/wg-data"
      ports:
          - "50007:50007/udp"

- ``/data/wg-data`` is a directory to store
  the information of the current angle of the wire-grid rotation,
  which is used in ``Wiregrid Kikusui Agent`` for feedback control of the rotation.
- ``ports`` is defined to receive the data from BeagleBoneBlack via UDP connection.

Description
-----------

Hardware Configurations
```````````````````````

The hardware-related variables are defined in ``wiregrid_encoder.py``:

    - COUNTER_INFO_LENGTH = 100
    - COUNTS_ON_BELT = 52000

These should be consistent with the script running in the BeagleBoneBlack,
and these numbers will rarely be changed because they depend on the hardware.

There are variables related to the data format in ``signal_parser.py``.
The variables should be consistent with the BeagleBoneBlack script as well.
They also will rarely be changed.


Agent API
---------

.. autoclass:: socs.agents.wiregrid_encoder.agent.WiregridEncoderAgent
    :members:
