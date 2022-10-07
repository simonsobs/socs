.. highlight:: rst

.. _smurf_file_emulator:

====================
Smurf File Emulator
====================

The Smurf File Emulator agent creates fake pysmurf and g3 files using the same
directory structure that we're currently archiving on simons1. This is for
DAQ end-to-end and bookbinder tests.

It has several tasks/processes that will exist in the ocs-pysmurf-controller,
and writes out fake files based on current examples of smurf anciliary data
that's present on simons1.

.. argparse::
    :filename: ../socs/agents/smurf_file_emulator/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````
Here is an example of the file-emulator site-configuration block::

   {'agent-class': 'SmurfFileEmulator',
    'instance-id': 'smurf-file-emulator',
    'arguments': [[
       '--stream-id', 'emulator',
       '--base-dir', '/path/to/fake/data/directory',
       '--file-duration', 60,
       '--nchans', 1024,
       '--sample-rate', 200,
       '--frame-len', 2
    ]]}


Note that if this is running in a docker container, the base-dir must be the
in-container path, so if you're mounting a directory to ``/data``, the base-dir
should just be ``/data``.

Docker Compose
``````````````

This agent doesn't really need to run in a docker container, but if you're so
inclined an example config entry is::

  ocs-smurf-file-emulator:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=smurf-file-emulator
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /path/to/fake/data/dir:/data

Agent API
---------

.. autoclass:: socs.agents.smurf_file_emulator.agent.SmurfFileEmulator
    :members:

Supporting API
---------------

.. autoclass:: socs.agents.smurf_file_emulator.agent.Tune
    :members:

.. autoclass:: socs.agents.smurf_file_emulator.agent.DataStreamer
    :members:

.. autoclass:: socs.agents.smurf_file_emulator.agent.G3FrameGenerator
    :members:
