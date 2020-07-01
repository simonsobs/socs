.. highlight:: rst

.. _lakeshore372:

=============
Lakeshore 372
=============

The Lakeshore 372 (LS372) units are used for 100 mK and 1K thermometer readout.
Basic functionality to interface and control an LS372 is provided by the
``socs.Lakeshore.Lakeshore372.py`` module.

.. argparse::
    :filename: ../agents/lakeshore372/LS372_agent.py
    :func: make_parser
    :prog: python3 LS372_agent.py

OCS Configuration
-----------------

To configure your Lakeshore 372 for use with OCS you need to add a
Lakeshore372Agent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'Lakeshore372Agent',
   'instance-id': 'LSA22YG',
   'arguments': [['--serial-number', 'LSA22YG'],
                 ['--ip-address', '10.10.10.2'],
                 ['--dwell-time-delay', 0]]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Configuration
--------------------

The Lakeshore 372 Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-LSA22YE:
    image: grumpy.physics.yale.edu/ocs-lakeshore372-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=LSA22YE"
      - "--site-hub=ws://127.0.0.1:8001/ws"
      - "--site-http=http://127.0.0.1:8001/call"

.. note::
    Since the 372 Agent container needs ``network_mode: "host"``, it must be
    configured to connect to the crossbar server as if it was on the host
    system. In this example the crossbar server is running on localhost,
    ``127.0.0.1``, but on your network this may be different.

To view the 372 temperatures data feed in the live monitor an accompanying
data-feed server will need to be run. An example of this configuration is::

  sisock-LSA22YE:
    image: grumpy.physics.yale.edu/sisock-data-feed-server:latest
    environment:
        TARGET: LSA22YE # match to instance-id of agent to monitor, used for data feed subscription
        NAME: 'LSA22YE' # will appear in sisock a front of field name
        DESCRIPTION: "LS372 with two ROXes for calibration."
        FEED: "temperatures"
    logging:
      options:
        max-size: "20m"
        max-file: "10"

For additional configuration see the sisock data-feed-server documentation.

.. note::
    The serial numbers here will need to be updated for your device.


Direct Communication
--------------------
Direct communication with the Lakeshore can be achieved without OCS, using the
``Lakeshore372.py`` module in ``socs/socs/Lakeshore/``. From that directory,
you can run a script like::

    from Lakeshore372 import LS372

    ls = LS372('10.10.10.2')

You can use the API detailed on this page to then interact with the Lakeshore.
Each Channel is given a Channel object in ``ls.channels``. You can query the
resistance measured on the currently active channel with::

    ls.get_active_channel().get_resistance_reading()

That should get you started with direct communication. The API is fairly full
featured. For any feature requests for functionality that might be missing,
please file a Github issue.

Agent API
---------

.. autoclass:: agents.lakeshore372.LS372_agent.LS372_Agent
    :members: init_lakeshore_task

Driver API
----------

For the API all methods should start with one of the following:

    * set - set a parameter of arbitary input (i.e. set_excitation)
    * get - get the status of a parameter (i.e. get_excitation)
    * enable - enable a boolean parameter (i.e. enable_autoscan)
    * disable - disbale a boolean parameter (i.e. disable_channel)

.. automodule:: socs.Lakeshore.Lakeshore372
    :members:
