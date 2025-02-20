.. highlight:: rst

.. _stimulator_thermometer:

============================
Stimulator Thermometer Agent
============================
This is an OCS agent to acquire temperature data of the stimulator.

.. argparse::
   :module: socs.agents.stimulator_thermometer.agent
   :func: make_parser
   :prog: agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent.

OCS Site Config
```````````````
To configure the stimulator thermometer agent we need to add a StimThermometerAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'StimThermometerAgent',
        'instance-id': 'stim_thermo',
        'arguments': [['--paths-spinode', [
          '/sys/bus/spi/devices/spi3.0/',
          '/sys/bus/spi/devices/spi3.1/',
          '/sys/bus/spi/devices/spi3.2/',
          '/sys/bus/spi/devices/spi3.3/']]]}

Description
-----------
The stimulator utilizes the MAX31856 and MAX31865 devices to read thermocouple and PT1000 sensors, respectively.
These devices are connected to the KR260 board within the stimulator readout box
via a Raspberry Pi-compatible pin header using a 4-wire SPI configuration.
The programmable logic (PL) of the KR260 is configured with an AXI SPI IP core
to facilitate SPI communication between the CPU and these devices.

The operating system on the KR260 CPU recognizes these devices through
a device tree overlay, as shown below::

   &axi_quad_spi{
    temperature-sensor@0 {
        compatible = "maxim,max31856";
        spi-max-frequency = <5000000>;
        reg = <0x0>;
        spi-cpha;
        thermocouple-type = <0x05>;
      };
   };

The compatible property is set to the corresponding device to load the appropriate driver.
After applying the device tree overlay, the devices can be accessed via the Industrial I/O (IIO) subsystem.
Temperature readings can then be obtained by accessing the corresponding files, such as:
``/sys/bus/iio/devices/iio:device2/in_temp_raw``.

The agent reads these files and publishes the acquired data to the feed.

Agent API
---------

.. autoclass:: socs.agents.stimulator_thermometer.agent.StimThermometerAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.stimulator_thermometer.drivers.StimThermoError
    :members:

.. autoclass:: socs.agents.stimulator_thermometer.drivers.Iio
    :members:

.. autoclass:: socs.agents.stimulator_thermometer.drivers.Max31856
    :members:

.. autoclass:: socs.agents.stimulator_thermometer.drivers.Max31865
    :members:
