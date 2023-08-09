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
    :filename: ../socs/agents/lakeshore372/agent.py
    :func: make_parser
    :prog: python3 agent.py

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
                 ['--mode', 'acq'],
                 ['--sample-heater', False],
                 ['--enable-control-chan'],
                 ['--configfile', 'ls372_config.yaml']]},


Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Lakeshore 372 Config
`````````````````````
A Lakeshore 372 configuration file allows the user to define device and channel
settings (autoscan, enable/disable, calibration curve, etc.) for each Lakeshore
372 in use within one .yaml file. Here is an example for how to build a
Lakeshore 372 configuration file::

    LSA22YG:
        device_settings:
          autoscan: 'off'
        channel:
          1:
             enable: 'on'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'on'
             resistance_range: 2e3
             dwell: 15 # seconds
             pause: 10 # seconds
             calibration_curve_num: 23
             temperature_coeff: 'negative'
          2:
             enable: 'off'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'off'
             resistance_range: 2.0e+3
             dwell: 10 # seconds
             pause: 3 # seconds
             calibration_curve_num: 28
             temperature_coeff: 'negative'
    LSA2761:
        device_settings:
          autoscan: 'on'
        channel:
          1:
             enable: 'on'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'on'
             resistance_range: 2.0e+3
             dwell: 15 # seconds
             pause: 10 # seconds
             calibration_curve_num: 33
             temperature_coeff: 'negative'
          2:
             enable: 'off'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'off'
             resistance_range: 2.0e+3
             dwell: 10 # seconds
             pause: 3 # seconds
             calibration_curve_num: 36
             temperature_coeff: 'negative'
          3:
             enable: 'on'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'on'
             resistance_range: 2.0e+3
             dwell: 15 # seconds
             pause: 10 # seconds
             calibration_curve_num: 34
             temperature_coeff: 'negative'
          4:
             enable: 'on'
             excitation_mode: 'voltage'
             excitation_value: 2.0e-6
             autorange: 'off'
             resistance_range: 2.0e+3
             dwell: 10 # seconds
             pause: 3 # seconds
             calibration_curve_num: 35
             temperature_coeff: 'negative'

.. note::
   For setting a 372 channel to a specific resistance range, be sure to check
   that autorange is set to 'off'. Else, the autorange setting will persist
   over your desired resistance range.

.. note::
   Make sure values like excitation and resistance are in float form as shown
   in the example. Ex: always 2.0e+3, never 2e3

Docker Compose
``````````````

The Lakeshore 372 Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-LSA22YG:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=LSA22YG
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

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

.. autoclass:: socs.agents.lakeshore372.agent.LS372_Agent
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
