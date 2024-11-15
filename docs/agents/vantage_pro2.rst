.. highlight:: rst

.. _vantagepro2:

==================
Vantage Pro2 Agent
==================

The Davis Instruments Vantage Pro2 is a weather system + monitor used to
acquire and readout weather data. The Vantage Pro2 monitor is connected to
the laboratory computer via usb cable and data is sent though that connection.
Here is the `VantagePro2 Operations manual`_.

.. argparse::
    :filename: ../socs/agents/vantagepro2/agent.py
    :func: make_parser
    :prog: python3 agent.py

.. _`VantagePro2 Operations manual`: https://www.davisinstruments.com/support/weather/download/VantageSerialProtocolDocs_v261.pdf

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Vantage Pro2 Agent we need to add a VantagePro2Agent block to
our ocs configuration file. Here is an example configuration block,
where we do not specify the port.
Note: One should first add the serial number of the VantagePro 2 device
to the udev file and create SYMLINK.
The Vendor ID is "10c4" and the Prodcut ID is "ea60" for the Vantage Pro2.
Here, we associate the vendor and product ID's with the SYMLINK 'VP2'.
So, we're setting the serial number argument as 'VP2'::

     {'agent-class': 'VantagePro2Agent',
       'instance-id': 'vantagepro2agent',
       'arguments': [['--mode', 'acq'],
                     ['--serial-number', 'VP2'],
                     ['--sample-freq', '0.5']]},

An example block of the udev rules file for the VantagePro 2 follows::

        SUBSYSTEM=="tty", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60",
                SYMLINK="VP2"


The agent will attempt to find the port that the Vantage Pro2 is connected to
based on the serial number.

Note the '--freq' argument specifies the sample frequency that the Vantage Pro2
Monitor collects weather data. The Vantage Pro2 and weather station can
sample weathervdata at a maximum sample frequency of 0.5 Hz.
The user can define slower sample frequencies if they so desire.

Docker Compose
``````````````

The Vantage Pro2 Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-vantage-pro2:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    command:
      - INSTANCE_ID=vantagepro2agent
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

Description
-----------
Out of the box, one just needs to connect the weather station to the
Vantage Pro2 monitor, and the monitor to the lab computer via usb.

The Vantage Pro2 monitor and weather station records many different
types of weather data:

- Barometer trend, the current 3 hour barometer trend.

  - -60 = Falling rapidly
  - -20 = Falling slowly
  - 0 = Steady
  - 20 = Rising slowly
  - 60 = Rising rapidly
  - 80 = No trend available
  - Any other value = The VantagePro2 does not have the 3 hours of data needed
    to determine the barometer trend.

- Barometer: Current barometer reading (Hg/1000)
- Inside Temperature: Temperatue in Fahrenheit (up to 10th of a degree)
- Inside Humidity: Relative humidity in percent
- Outside Temperature: Temperature in Fahrenheit (up to 10th of a degree)
- Wind Speed: Wind speed in miles per hour
- 10 min average wind speed: 10 minute average wind speed in miles per hour
- Wind Direction: From 1-360 degrees

  - 0 = No wind direction data
  - 90 = East
  - 180 = South
  - 270 = West
  - 360 = North

- Extra Temperatures: VantagePro2 can read temperature from up to 7 extra
  temperature stations. However, they are offset by negative 90 degrees fahrenheit.
  So, a value of 100 is: ``100 - 90 = 10`` degrees fahrenheit.
- Soil Temperatures: Four soil temperature sensors, in the same format as the
  extra temperatures format listed above.
- Leaf Temperatures: Four leaf temperature sensors, in the same format as the
  extra temperatures format listed above.
- Outside Humidity: Relativie humidity in percent
- Extra Humidities: Realtive humidity in percent for 7 humidity stations
- Rain Rate: Number of rain clicks (mm per hour)
- UV: "Unit is in UV index"
- Solar Radiation: Units in watt/meter^2
- Storm Rain: Stored in 100th of an inch
- Start Date of Current storm: Gives month, date, and year (offset by 2000)
- Day Rain: Number of rain clicks (0.1in or 0.2mm)/hour in the past day
- Month Rain: Number of rain clicks (0.1in or 0.2mm)/hour in the past month
- Year Rain: Number of rain clicks (0.1in or 0.2mm)/hour in the past year
- Day ET: 1000th of an inch
- Month ET: 1000th of an inch
- Year ET: 1000th of an inch
- Soil Moistures: In centibar, supports 4 soil sensors
- Leaf Wetnesses: Scale from 0-15. Supports 4 leaf sensors

  - 0 = Very dry
  - 15 = Very wet

- Inside Alarms: Currently active inside alarms
- Rain Alarms: Currently active rain alarms
- Outside Alarms: Currently active outside alarms
- Outside Humidity Alarms: Currently active humidity alarms
- Extra Temp/Hum Alarms: Currently active extra temperature/humidity alarms
- Soil & Leaf Alarms: Currently active soil/leaf alarms
- Console Battery Voltage: Voltage = ``((Data x 300)/512)/100.0``
- Time of Sunrise: Time is stored as hour x 100 + min
- Time of Sunset: Time is stored as hour x 100 + min

Agent API
---------

.. autoclass:: socs.agents.vantagepro2.agent.VantagePro2Agent
    :members:
