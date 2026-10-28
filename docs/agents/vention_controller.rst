.. highlight:: rst

.. _vention_controller:

========================
Vention Controller Agent
========================

.. image:: https://img.shields.io/badge/AI-free-green
   :alt: Agent written without AI assistance

The Vention Controller Agent provides motion control and telemetry readout for
the Vention MachineMotion AI controller. When used to control the Simons Observatory LAT FTS-coupling optics system, this agent controls four linear actuators (two of which are synchronized) which correspond to three independent axes. These axes are used to move the FTS hardware to enable end-to-end passband measurements of the entire LATR.


.. argparse::
    :filename: ../socs/agents/vention_controller/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
------------

Vention's `machinelogic <https://pypi.org/project/machine-logic-sdk/>`_ package must be installed to use this Agent. This can be installed via:

.. code-block:: bash

    $ pip install machine-logic-sdk

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure your Vention motor controller for use with OCS you need to add a
VentionControllerAgent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'VentionControllerAgent',
   'instance-id': 'latcouplingoptics',
    'arguments': ['--ip', '192.168.10.134',
                  '--mode', 'acq']}

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.


Vention Controller Config
`````````````````````````

The configuration file for the Vention controller is uploaded directly to the hardware and is therefore not handled by this OCS agent. It is a yaml file which specifies the axes and their properties, and can be generated automatically on the Vention website from the design file.


Docker Compose
``````````````

The Vention Controller Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-vention-agent:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=latcouplingoptics
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Example Clients
---------------

Below are some example use cases for using this agent.

.. note::
   The examples below assume the Vention controller is configured with 3 independent axes named "X", "Y", and "Z", as they are in the Simons Observatory LAT FTS-coupling optics system.

Homing Procedure
````````````````

The Vention axes are equipped with proximity sensors that are used to define an absolute position reference for each axis. The homing procedure moves each axis, in (x,y,z) order, to its "home" sensor. The velocity and acceleration settings for the homing procedure are set by the hardware's configuration file rather than by :code:`set_motion_profile`. Therefore, the homing motion settings can only be changed by modifying the configuration file and re-uploading it to the hardware.

Homing can be performed simply by calling the :code:`home` task::

  client.home()

In addition to moving each axis, the :code:`home` task also sets the absolute position of each axis to zero. This is important for ensuring that subsequent motion commands are interpreted correctly; absolute positions are only meaningful after :code:`home` has been run. Therefore, it is recommended to run :code:`home` at the beginning of any client script that will issue motion commands.

Motion Commands
````````````````

Before issuing any motion commands, the velocity (mm/s) and acceleration (mm/s^2) for all subsequent moves can be set using :code:`set_motion_profile`::

  client.set_motion_profile(velocity=20.0, acceleration=50.0)

Alternatively, one can specify the velocity and acceleration for each individual move command using the optional :code:`velocity` and :code:`acceleration` keyword arguments. These arguments override the values set by :code:`set_motion_profile` for that specific move command.

There are two types of motion commands: :code:`set_absolute_position` and :code:`set_relative_position`. Both commands take their :code:`distances` argument in mm and only return after the motion is complete. The former moves the axes to a specified absolute (x, y, z) position, while the latter moves the axes by a specified relative (x, y, z) distance from their current position. The "positive" direction is set in the hardware's configuration file and always points from the home to the end sensor.

Example of a client script that sets a motion profile, an absolute position, and then a relative position::

  client.set_motion_profile(velocity=20.0, acceleration=50.0)
  client.set_absolute_position(distances=[100, 100, 100])
  client.set_relative_position(distances=[50, 50, -25])

Agent API
---------

.. autoclass:: socs.agents.vention_controller.agent.VentionControllerAgent
    :members:
