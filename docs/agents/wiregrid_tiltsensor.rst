.. highlight:: rst

.. _wiregrid_tiltsensor:

==========================
Wiregrid Tilt Sensor Agent
==========================

The Wiregrid Tilt Sensor Agent records the wire-grid tilt sensor outputs
related to the tilt angle of the wire-grid plane along the gravitaional direction.
There is two types of tilt sensors, DWL and sherborne.
The tilt sensor data is sent via serial-to-ethernet converter.
The converter is linked to the tilt sensor
via RS-422(DWL) or RS-485(sherborne), D-sub 9-pin cable.
The agent communicates with the converter via Ethernet.

.. argparse::
   :filename: ../socs/agents/wiregrid_tiltsensor/agent.py
   :func: make_parser
   :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WiregridTiltSensorAgent',
     'instance-id': 'wg-tilt-sensor',
     'arguments': ['--ip-address', '192.168.11.27',
                   '--port', '32',
                   '--sensor-type', 'DWL']},

- ``ip-address`` is an IP address of the serial-to-ethernet converter.
- ``port`` is an asigned port for the tilt sensor.
  (The converter has four D-sub ports, 23, 26, 29, 32, to control
  multiple devices connected via serial communication.
  Communicating device is determined by the ethernet port number of the converter.)
- ``sensor_type`` represents the type of tilt sensor to communicate with.
  We have the two types of tilt sensor, DWL and sherborne.
  Available values of this argument are only 'DWL' or 'sherborne',
  and depend on SATp.

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-wg-tilt-sensor-agent:
      image: simonsobs/socs:latest
      hostname: ocs-docker
      network_mode: "host"
      command:
        - INSTANCE_ID=wg-tilt-sensor
      volumes:
        - ${OCS_CONFIG_DIR}:/config:ro

- Since the agent within the container needs to communicate with hardware on the
  host network you must use ``network_mode: "host"`` in your compose file.

Agent API
---------

.. autoclass:: socs.agents.wiregrid_tiltsensor.agent.WiregridTiltSensorAgent
    :members:
