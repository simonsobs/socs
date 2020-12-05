.. highlight:: rst

.. _vantagepro2:

=============
Vantage Pro2 Agent
=============

The Davis Instruments Vantage Pro2 is a weather system + monitor used to 
acquire and readout weather data. The Vantage Pro2 monitor is connected to
the labratory computer via usb cable and data is sent though that connection.

.. argparse::
    :filename: ../agents/vantagePro2_agent/vantage_pro2_agent.py
    :func: make_parser
    :prog: python3 vantage_pro2_agent.py

Description
-----------
Out of the box, one just needs to connect the weather station to the 
Vantage Pro2 monitor, and the monitor to the lab computer via usb. As long as
the Vantage Pro2 monitor is on, the intitialize and data acquisition tasks 
should work "out of the box", as it where.

The Vantage Pro2 monitor and weather station records 

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Vantage Pro2 Agent we need to add a VantagePro2Agent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

     {'agent-class': 'VantagePro2Agent',
       'instance-id': 'vantagepro2agent',
       'arguments': [['--port', '/dev/ttyUSB0'],
                     ['--mode', 'acq'],
                     ['--freq', '2']]},
   
You should know the port, or usb connection, that the Vantage Pro2 is connected to.
Assign that location to the '--port' argument.

Note, the '--freq' argument specifies the sample frequency that the Vantage Pro2 
Monitor collects weather data. The Vantage Pro2 and weather station can sample weather
data at a maximum sample frequency of 1/2 Hz. The user can define lower 
sample frequencies if they so desire.  

Docker
``````
The Vantage Pro2 Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-vantage-pro2:
    build: /socs/agents/vantagePro2_agent

    environment:
      TARGET: VantagePro2Agent
      NAME: 'Vantage Pro2'
      DESCRIPTION: "Vantage Pro2 Weather Station Monitor"
      FEED: "weather_data"
    volumes:
      - ./:/config:ro
    command:
      - "--instance-id=vantagepro2agent"
      - "--site-hub=ws://sisock-crossbar:8001/ws"
      - "--site-http=http://sisock-crossbar:8001/call"
    devices:
      - "/dev/ttyUSB0:/dev/ttyUSB0"

Where the device location is listed under "devices:"

Agent API
---------

.. autoclass:: agents.vantagePro2_agent.vantage_pro2_agent.VantagePro2Agent
    :members: init_vantagePro2_task, start_acq
