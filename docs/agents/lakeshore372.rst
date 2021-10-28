.. highlight:: rst

.. _lakeshore372:

=============
Lakeshore 372
=============

The Lakeshore 372 Agent interfaces with the Lakeshore 372 (LS372) hardware to
perform 100 mK and 1K thermometer readout and control heater output. Basic
functionality to interface and control an LS372 is provided by the
:ref:`372_driver`.

.. argparse::
    :filename: ../agents/lakeshore372/LS372_agent.py
    :func: make_parser
    :prog: python3 LS372_agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure your Lakeshore 372 for use with OCS you need to add a
Lakeshore372Agent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'Lakeshore372Agent',
   'instance-id': 'LSA22YG',
   'arguments': [['--serial-number', 'LSA22YG'],
                 ['--ip-address', '10.10.10.2'],
                 ['--dwell-time-delay', 0],
                 ['--auto-acquire'],
                 ['--sample-heater', False],
                 ['--enable-control-chan']]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Compose
``````````````

The Lakeshore 372 Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-LSA22YE:
    image: simonsobs/ocs-lakeshore372-agent:latest
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

.. note::
    The serial numbers here will need to be updated for your device.

Description
-----------

The Lakeshore 372 provides several connection options for communicating
remotely with the hardware. For the Lakeshore 372 Agent we have written the
interface for communication via Ethernet cable. When extending the Agent it can
often be useful to directly communicate with the 372 for testing. This is
described in the following section.

Direct Communication
````````````````````
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
    :members:

.. _372_driver:

Supporting APIs
---------------

For the API all methods should start with one of the following:

    * set - set a parameter of arbitary input (i.e. set_excitation)
    * get - get the status of a parameter (i.e. get_excitation)
    * enable - enable a boolean parameter (i.e. enable_autoscan)
    * disable - disbale a boolean parameter (i.e. disable_channel)

.. automodule:: socs.Lakeshore.Lakeshore372
    :members:
