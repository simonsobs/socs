.. highlight:: rst

.. _lakeshore336:

=============
Lakeshore 336
=============

The Lakeshore 336 Agent interfaces with the Lakeshore 336 (LS336) hardware to
perform temperature monitoring and servoing on the LS336's four channels.
This setup is currently primarily being used for controlling a cold load.
Basic functionality to interface with and control an LS336 is provided by
the :ref:`336_driver`.

.. argparse::
    :filename: ../socs/agents/lakeshore336/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are some configuration files for the OCS config file and for running the
Agent in a Docker container.

OCS Site Config
```````````````

To configure your Lakeshore 336 for use with OCS, you need to add a
Lakeshore336Agent block to your OCS configuration file. Here is an example
configuration block::

  {'agent-class': 'Lakeshore336Agent',
   'instance-id': 'LSA2833',
   'arguments': [['--serial-number', 'LSA2833'],
                 ['--ip-address', '10.10.10.2'],
                 ['--f-sample', 0.1],
                 ['--threshold', 0.05],
                 ['--window', 600],
                 ['--auto-acquire']]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Compose
``````````````

The Lakeshore 336 agent should be configured to run in a Docker container.
An example configuration is::

  ocs-LSA2833:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=LSA2833
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

.. note::
    Since the 336 Agent container needs ``network_mode: "host"``, it must be
    configured to connect to the crossbar server as if it was on the host
    system. In this example the crossbar server is running on localhost,
    ``127.0.0.1``, but on your network this may be different.

.. note::
    The serial numbers here will need to be updated for your device.

Description
-----------

Like the Lakeshore 372, direct communication via ethernet is possible
with the Lakeshore 336. Please see the Lakeshore 372 Agent documentation
for more information about direct communication and the following APIs
to see which methods are available in the agent and the underlying
Lakeshore336.py script.

Agent API
---------

.. autoclass:: socs.agents.lakeshore336.agent.LS336_Agent
    :members:

.. _336_driver:

Supporting APIs
---------------

.. automodule:: socs.Lakeshore.Lakeshore336
    :members:
