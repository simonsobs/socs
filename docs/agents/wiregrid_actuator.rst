.. highlight:: rst

.. _wiregrid_actuator:

=======================
Wiregrid Actuator Agent
=======================

The Wiregrid Actuator Agent controls the linear actuator
to insert or eject the wire-grid via a GALIL motor controller.
It communicates with the controller via an ethernet.
It also reads ON/OFF of the limit-switches on the ends of the actuators
and lock/unlock the stoppers to lock/unlock the actuators.

.. argparse::
   :filename: ../socs/agents/wiregrid_actuator/agent.py
   :func: make_parser
   :prog: python3 agent.py

Dependencies
------------

This agent depends on GALIL controller libraries: gclib.
gclib requires installation of other libraries and gclib itself
and starting services(dbus, avahi-daemon, and gcapsd) in the docker.
These preparations are automatically made in Dockerfile and wg-actuator-entrypoint.sh.
Reference links for gclib:

- Installation via apt: https://www.galil.com/sw/pub/all/doc/global/install/linux/debian/
- Python library installation: https://www.galil.com/sw/pub/all/doc/gclib/html/

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WiregridActuatorAgent',
     'instance-id': 'wgactuator',
     'arguments': [['--ip-address', '10.10.10.73']]},

Docker Compose
``````````````

An example docker compose configuration::

    ocs-wgactuator-agent:
        image: simonsobs/ocs-wgactuator-agent:latest
        hostname: ocs-docker
        network_mode: "host"
        environment:
          - INSTANCE_ID=wgactuator
        volumes:
          - ${OCS_CONFIG_DIR}:/config:ro

- Since the agent within the container needs to communicate with hardware on the
  host network you must use ``network_mode: "host"`` in your compose file.

Description
-----------

Functions
`````````

The agent has many functions, however most of them are for testing.
The main functions are ``insert()`` and ``eject()``.

**Main Functions**
 - insert(): Insert the wire-grid into the inside of the forebaffle, which includes unlocking the stoppers
 - eject(): Eject the wire-grid from the inside of the forebaffle, which includes unlocking the stoppers

In the both of the functions, after the inserting/ejecting, the stopper locks the actuators again.
However, the motor power is not turned ON or OFF during the both functions.

The parameter details are here:

- speedrate: Actuator speed rate [0.0, 5.0] (default: 1.0)

**Test Functions**
 - check_limitswitch(): Check ON/OFF of the limit switches
 - check_stopper(): Check ON/OFF (lock/unlock) of the stoppers
 - insert_homing(): Insert very slowly
 - eject_homing(): Eject very slowly
 - insert_test(): Insert in a test mode
 - eject_test(): Eject in a test mode
 - motor_on(): Power ON the actuator motors
 - motor_off(): Power OFF the actuator motors
   (CAUTION: Take care of using this function
   since powering OFF the motor means
   that the wire-grid can slide down by its gravity if the stoppers do NOT lock the actuators.)
 - stop(): Stop the motion of the actuators (Change a STOP flag in Actuator class to True)
 - release(): Release the agent to receive the functions if it is locked in the software
   (Change a STOP flag in Actuator class to False)
 - reconnect(): Reconnect to the actuator controller

In the test mode, you can choose the moving distance [mm] and speed rate.
The parameter details are here:

- distance: Actuator moving distance [mm] (default: 10)
- speedrate: Actuator speed rate [0.0, 5.0] (default: 0.2)


Hardware Configurations
```````````````````````

There are several limit-switches and stoppers.
These list are configured in ``limitswitch_config.py`` and ``stopper_config.py``.


Agent API
---------

.. autoclass:: socs.agents.wiregrid_actuator.agent.WiregridActuatorAgent
    :members:

Example Clients
---------------

Below is an example client to insert and eject the actuator::

    from ocs.ocs_client import OCSClient
    wgactuator = OCSClient('wgactuator')

    # Insert the actuator
    wgactuator.insert()

    # Eject the actuator
    wgactuator.eject()

Supporting APIs
---------------

.. autoclass:: socs.agents.wiregrid_actuator.drivers.Actuator.Actuator
    :members:

.. autoclass:: socs.agents.wiregrid_actuator.drivers.DigitalIO.DigitalIO
    :members:
