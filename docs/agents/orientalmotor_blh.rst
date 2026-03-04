.. highlight:: rst

.. _orientalmotor_blh:

========================
Oriental Motor BLH Agent
========================

This agent is designed to interface with Oriental Motor's BLH series motor controllers.
Only controllers with a model number that includes '-KD' are compatible with this agent.
The controller is identified as a serial port,
and you can specify the device file using the `--port` option in the argument.
On Ubuntu, the device is recognized without requiring any driver installation and will
appear as `/dev/ttyACM*` (e.g., `/dev/ttyACM0`, `/dev/ttyACM1`, etc.), where the number varies
depending on the system.
A symbolic link to the device file is also available under `/dev/serial/by-id/` as
`usb-ORIENTAL_MOTOR_CO._LTD._ORIENTAL_MOTOR_USB-Deviice_0000000000-if00`.

.. argparse::
    :filename: ../socs/agents/orientalmotor_blh/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file.

OCS Site Config
`````````````````````

An example site-config-file block::

    {'agent-class': 'BLHAgent',
     'instance-id': 'blh',
     'arguments': [ '--port', '/dev/ttyACM0']
     },

Description
--------------

The LAT stimulator employs a BLH-series motor controller to rotate the chopper.
This agent is responsible for starting and stopping the motor,
monitoring the rotation speed,and controlling operational parameters
such as the rotation speed.
To prevent the controller from stopping the rotation due to inactivity over a certain period,
this agent continuously reads the rotation speed during its operation.

The acceleration and deceleration of the motor can be controlled
by specifying the time required to reach the desired rotation speed.

Agent API
---------

.. autoclass:: socs.agents.orientalmotor_blh.agent.BLHAgent
   :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.orientalmotor_blh.drivers.BLH
   :members:
