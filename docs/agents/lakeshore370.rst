.. highlight:: rst

.. _lakeshore370:

=============
Lakeshore 370
=============

The Lakeshore 370 (LS370) units are an older version of the Lakshore 372, used
for 100 mK and 1K thermometer readout.  Basic functionality to interface and
control an LS370 is provided by the
``socs.Lakeshore.Lakeshore370.py`` module.

.. argparse::
    :filename: ../socs/agents/lakeshore370/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

OCS Site Config
```````````````

To configure your Lakeshore 370 for use with OCS you need to add a
Lakeshore370Agent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'Lakeshore370Agent',
   'instance-id': 'LSA22YG',
   'arguments': [['--serial-number', 'LSA22YG'],
                 ['--port', '/dev/ttyUSB1'],
                 ['--dwell-time-delay', 0]]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Compose
``````````````

The Lakeshore 370 Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-LSA22YG:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=LSA22YG
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    devices:
      - "/dev/ttyUSB1:/dev/ttyUSB1"

.. note::
    The serial numbers here will need to be updated for your device.

.. note::
    The device path may differ on your machine, and if only using the ttyUSB
    value as shown here, is not guaranteed to be static.

Description
-----------

Direct Communication
````````````````````
Direct communication with the Lakeshore can be achieved without OCS, using the
``Lakeshore370.py`` module in ``socs/socs/Lakeshore/``. From that directory,
you can run a script like::

    from Lakeshore370 import LS370

    ls = LS370('/dev/ttyUSB1')

You can use the API detailed on this page to then interact with the Lakeshore.
Each Channel is given a Channel object in ``ls.channels``. You can query the
resistance measured on the currently active channel with::

    ls.get_active_channel().get_resistance_reading()

That should get you started with direct communication. The API is fairly full
featured. For any feature requests for functionality that might be missing,
please file a Github issue.

Agent API
---------

.. autoclass:: socs.agents.lakeshore370.agent.LS370_Agent
    :members:

Supporting APIs
---------------

For the API all methods should start with one of the following:

    * set - set a parameter of arbitary input (i.e. set_excitation)
    * get - get the status of a parameter (i.e. get_excitation)
    * enable - enable a boolean parameter (i.e. enable_autoscan)
    * disable - disbale a boolean parameter (i.e. disable_channel)

.. automodule:: socs.Lakeshore.Lakeshore370
    :members:
