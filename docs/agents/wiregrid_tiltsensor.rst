.. highlight:: rst

.. _wiregrid_tiltsensor:

==========================
Wiregrid Tilt Sensor Agent
==========================

.. image:: https://img.shields.io/badge/AI-assisted-orange
   :alt: Agent written with AI assistance

The Wiregrid Tilt Sensor Agent records the wire-grid tilt sensor outputs
related to the tilt angle of the wire-grid plane along the gravitational direction.
There are three types of tilt sensors, DWL, sherborne and Pacico SLP2.
The tilt sensor data is sent via serial-to-ethernet converter.
The converter is linked to the tilt sensor
via RS-422(DWL), RS-485(sherborne) or RS-232 (SLP2).
The agent communicates with the converter via Ethernet.

The agent records the X- and Y-axis angles of the tilt sensor.
For SLP2, it also records the temperature of the sensor.
SLP2 has a single temperature sensor common to both axes,
so the temperature is recorded as one value (``temperature``)
instead of ``temperatureX`` and ``temperatureY``.
If the agent fails to get data from the sensor
(e.g. an invalid reply or a dropped connection),
it closes the connection and reconnects to the sensor in the next loop.

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
- ``port`` is an assigned port for the tilt sensor.
  (The converter has four D-sub ports, 23, 26, 29, 32, to control
  multiple devices connected via serial communication.
  Communicating device is determined by the ethernet port number of the converter.)
- ``sensor_type`` represents the type of tilt sensor to communicate with.
  We have the three types of tilt sensor, DWL, sherborne and Pacico SLP2.
  Available values of this argument are only 'DWL', 'sherborne' or 'slp2',
  and depend on SATp.
  Other values are rejected when the agent starts.
  The ``reset`` task is available only for sherborne.

Docker Compose
``````````````

An example docker compose configuration::

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
