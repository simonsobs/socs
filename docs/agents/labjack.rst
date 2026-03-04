.. highlight:: rst

.. _labjack:

=============
LabJack Agent
=============

LabJacks are generic devices for interfacing with different sensors, providing
analog and digital inputs and outputs. They are then commanded and queried over
Ethernet.

.. argparse::
    :filename: ../socs/agents/labjack/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
------------

* `labjack-ljm <https://pypi.org/project/labjack-ljm/>`_ - LabJack LJM Library

While there is the above PyPI package for the LJM library, it does not provide
the ``libLabJackM.so`` shared object file that is needed. This can be obtained
by running the LJM installer provided on the `LabJack website
<https://labjack.com/support/software/api/ljm>`_. You can do so by running::

    $ wget https://labjack.com/sites/default/files/software/labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
    $ tar zxf ./labjack_ljm_minimal_2020_03_30_x86_64_beta.tar.gz
    $ ./labjack_ljm_minimal_2020_03_30_x86_64/labjack_ljm_installer.run -- --no-restart-device-rules

.. note::
    This library is bundled in to the socs base Docker image. If you are running
    this Agent in Docker you do *not* also need to install the library on the
    host system.

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the LabJack Agent we need to add a LabJackAgent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

        {'agent-class': 'LabJackAgent',
         'instance-id': 'labjack',
         'arguments':[
           ['--ip-address', '10.10.10.150'],
           ['--active-channels', ['AIN0', 'AIN1', 'AIN2']],
           ['--function-file', 'labjack-functions.yaml'],
           ['--mode', 'acq'],
           ['--sampling-frequency', '700'],
           ]},

You should assign your LabJack a static IP, you'll need to know that here.
The 'active-channels' argument specifies the channels that will be read out.
It can be a list, 'T7-all', or 'T4-all'. The latter two read out all
14 or 12 analog channels on the T7 and T4, respectively. 'sampling_frequency'
is in Hz, and has been tested sucessfully from 0.1 to 5000 Hz. To avoid
high sample rates potentially clogging up live monitoring, the main feed
doesn't get published to influxdb. Instead influx gets a seperate feed
downsampled to a maximum of 1Hz. Both the main and downsampled feeds are
published to g3 files.

The 'function-file' argument specifies the labjack configuration file, which
is located in your OCS configuration directory. This allows analog voltage
inputs on the labjack to be converted to different units. Here is an example
labjack configuration file::

    AIN0:
        user_defined: 'False'
        type: "MKS390"

    AIN1:
        user_defined: 'False'
        type: 'warm_therm'

    AIN2:
        user_defined: 'True'
        units: 'Ohms'
        function: '(2.5-v)*10000/v'

In this example, channels AIN0 and AIN1 are hooked up to the MKS390 pressure
`gauge`_ and a `thermistor`_ from the SO-specified warm thermometry setup,
respectively. Since these are defined functions in the LabJackFunctions class,
specifying the name of their method is all that is needed. AIN2 shows how to
define a custom function. In this case, the user specifies the units and the
function itself, which takes the input voltage 'v' as the only argument.

.. _gauge: https://www.mksinst.com/f/390-micro-ion-atm-modular-vacuum-gauge
.. _thermistor: https://docs.rs-online.com/c868/0900766b8142cdef.pdf

.. note::
    The (lower-case) letter 'v' must be used when writing user-defined
    functions. No other variable will be parsed correctly.

Docker Compose
``````````````

The LabJack Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-labjack:
    image: simonsobs/socs:latest
    <<: *log-options
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=labjack
    volumes:
      - ${OCS_CONFIG_DIR}:/config

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Custom Register Readout
-----------------------
LabJack has many other registers available to access besides just the voltages
on AIN# which we use in the `mode=acq` option of this agent to readout directly
or convert to useful units using the functions module. These extra registers
however cannot be streamed out using the `ljstream` module which is the
code that enables streaming channels at up to O(kHz) sample rate. Because
ljstream cannot be used for these registers, and the sample rate is much lower
we implemented a different acquisition mode, `mode=acq_reg`, to access these
registers at slower sample rates.

The main registers that we have used are called `AIN Extended Features`_ and
provide readout of a number of standard thermometers (Thermocouples, RTDs,
and Thermistors) as well as some other features such as reporting the offset,
slope, RMS, averages, min, or max of one of the AINs. Our main usage so far
has been for the readout of thermocouples which allow a much larger temperature
range. Importantly, thermocouple type J is used to read out the very high
temperature (~1000C) ceramic heaters that serve as thermal sources for optical
measurements. Thermocouples tend to have a dependence on lead resistance and are
sensitive to drift so the labjack has some internal drift compensation using an
internal cold junction sensor that it reads in along with the raw voltages to
calculate the temperature of the thermocouple.

These extended feature registers can be configured to readout our standard SO warm
thermometers (PT1000 RTDs) and do the conversion to temperature internally. However,
there is less benefit to using this method since those registers are just
interpolating a calibration curve which is essentially the same as the calculations
applied when `warm_therm` is specified in the functions file. The configuration of
custom registers on one of the AINs is done through the `Kipling`_ software in
particular a description of how to setup the `AIN#_EF_READ_A` register to read out
a thermocouple can be found on `this page`_.

There are also other registers that can be accessed through this method such as
ethernet settings, power setting, internal offset currents, and clock information to
name a few. A full set of registers can be found on the labjack website with many listed
on the `Modbus Map`_ page.

.. _AIN Extended Features: https://labjack.com/support/datasheets/t-series/ain/extended-features
.. _Kipling: https://labjack.com/support/software/applications/t-series/kipling
.. _this page: https://labjack.com/support/software/applications/t-series/kipling/register-matrix/configuring-reading-thermocouple
.. _Modbus Map: https://labjack.com/support/software/api/modbus/modbus-map

Example Client
--------------
Since labjack functionality is currently limited to acquiring data, which can
enabled on startup, users are likely to rarely need a client. This example
shows the basic acquisition functionality:

.. code-block:: python

    # Initialize the labjack
    from ocs import matched_client
    lj = matched_client.MatchedClient('labjack')
    lj.init_labjack.start()
    lj.init_labjack.wait()

    # Start data acquisiton
    status, msg, session = lj.acq.start(sampling_frequency=10)
    print(session)

    # Get the current data values 1 second after starting acquistion
    import time
    time.sleep(1)
    status, message, session = lj.acq.status()
    print(session["data"])

    # Stop acqusition
    lj.acq.stop()
    lj.acq.wait()


Agent API
---------

.. autoclass:: socs.agents.labjack.agent.LabJackAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.labjack.agent.LabJackFunctions
    :members:
