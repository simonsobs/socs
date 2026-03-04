.. highlight:: rst

.. _galil_axis:

================
Galil Axis Agent
================

The Galil Axis Agent provides motion control and telemetry readout for
the Galil DMC motor controller. When used in the Simons Observatory SAT Coupling
Optics system, the agent controls four axes—two linear and two angular—that move
the hardware as needed to perform detector passband measurements.


.. argparse::
    :filename: ../socs/agents/galil_axis/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure your Galil axis motor controller for use with OCS you need to add a
GalilAxisAgent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'GalilAxisAgent',
   'instance-id': 'satcouplingoptics',
                 ['--ip', '10.120.1.6',
                  '--configfile', 'axes_config.yaml',
                  '--input_config', True,
                  '--mode', 'acq']}


Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

.. note::
   The :code:`input_config` argument is a boolean flag. When :code:`True`, the
   :code:`init` task loads and applies all motor-controller settings from
   the agent’s configuration file (see Galil Motor Axis Config below) to
   bring the controller and its axes into the desired state.


Galil Axis Config
`````````````````
A Galil axis configuration file defines the motion settings, motor
parameters, and brake mappings for each controlled axis. This allows the user
to easily adapt to different hardware configurations or coordinate multiple
axes (e.g., A, B, C, D) during operation::


        galil:
          motorsettings:
            countspermm: 4000
            countsperdeg: 2000
          limitsetting:
            polarity: '1'
            disable_limits:
              B: '3'
              D: '3'
          brakes:
            output_map:
              A: '1'
              B: '2'
              C: '3'
              D: '4'
          motorconfigparams:
            A:              # linear axis
              MT: '1'
              OE: '1'
              AG: '2'
              TL: '5'
              AU: '9'
            B:              # linear axis
              MT: '1'
              OE: '1'
              AG: '2'
              TL: '5'
              AU: '9'
            C:              # rotary axis
              MT: '1'
              OE: '1'
              AG: '2'
              TL: '5'
              AU: '9'
            D:              # rotary axis
              MT: '1'
              OE: '1'
              AG: '2'
              TL: '5'
              AU: '9'
          initaxisparams:
            BA: 'True'          # if True, will drive motors for each axis at 3V (BZ) for prepping for servo'd motion
            BM: '3276.8'
            BZ: '3'
          dwell_times:
            first_ms: '1000'
            second_ms: '1500'



Docker Compose
``````````````

The Galil Axis Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-galil-agent:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=satcouplingoptics
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Example Clients
---------------

Below are some example use cases for using this agent.

.. note::
   The examples below assume the Galil motor controller has sinusoidal amplifers,
   limit switches, and brakes (i.e., the Galil motor controllers used for the
   SAT coupling optics system)

Updating the config file
`````````````````````````

Though the agent can be configured to initialize the axes via the :code:`input_config`
boolean parameter in the OCS site config file, any changes made to the
configuration file after agent startup will require reloading it. The following
client command is used to update the motor controller settings accordingly::


  client.input_configfile(configfile='axes_config.yaml')

.. note::
   It is important to call the :code:`input_configfile` task even if the only update to
   the configuration file is a change to :code:`countspermm` or :code:`countsperdeg`, since
   these calibration values are necessary for commanding axis motion in physical
   units (mm/deg) rather than raw encoder counts.

Homing Procedure
````````````````

The SAT coupling optics Galil axes are equipped with limit switches, so
the chosen homing procedure is to move each axis continuously until it is
stopped by its limit switch. When the axis is forced to stop at the switch,
that raw encoder position should then be defined as :code:`0`.

To continuously move an axis, we use :code:`set_jog_speed` to define the speed at
which the axis will jog::

  client.set_jog_speed(axis='A', speed=5000.0)

Here, :code:`5000.0` is in units of counts/sec. Note that the speed set through :code:`set_jog_speed`
is always specified in counts/sec, unlike other tasks that alow motion in physical units
of millimeter or degrees (e.g., :code:`set_relative_position` or :code:`set_absolute_position`).

To begin motion::

  client.begin_axis_motion(axis='A')

After the axis stops at the limit switch, we define that position using::

  client.define_position(axis='A', val=0.00)


Gearing Settings
````````````````

The following tasks are used to define leader–follower relationships between axes.
For the SAT coupling optics system, axes A and B are the linear pair, and axes C and D are the
angular pair. In this configuration, A is the leader for B, and C is the leader for D.

The gearing **ratio** determines the velocity at which each follower axis moves relative to its
leader. For example, a ratio of :code:`1` means that B will follow A at the exact same speed defined
for A. A ratio of :code:`-1` means the follower moves at the same speed scale but in the opposite direction.

Once the leader–follower mapping and gearing ratios are set, commanding
motion on the leader (e.g., A) will cause both A and B to move. If this does
not occur, stop motion and query the gearing ratio for the relevant axes.

When querying the ratio, the expected response for a leader axis is :code:`0`, since leaders do not
follow any other axis. The follower axis should return the ratio you set (e.g., 1 for B).

Occasionally, the Galil motor controller may lose the gearing ratio values while still
correctly remembering the leader/follower assignments. If a gearing-ratio query for the
follower axis returns :code:`0`, reapply the gearing ratio.

Example usage of defining leader/follower axes and the gearing ratio::

  # configure A and C as the leader axes
  client.set_gearing(order=',A,C')
  client.set_gearing_ratio(order=',-1,1')

Here, the second field corresponds to B and the fourth field corresponds to D.

Another example using axes E and F for a 6-axis Galil motor controller system::

  # using axes E and F
  client.set_gearing(order=',,,,,E')
  client.set_gearing_ratio(order=',,,,,1')

In this case, F (the sixth position) follows E with a ratio of :code:`1`.


.. note::
   The :code:`order` argument encodes leader–follower relationships---each
   comma-delimited field corresponds to one axis in alphabetical order. An empty field
   means the axis is independent (i.e., not following another axis),
   while a non-empty field specifies which axis it should follow.

To query the gearing ratio::

  >>> response = client.get_gearing_ratio(axis='F')
  >>> print(response)
  OCSReply: OK : Operation "get_gearing_ratio" is currently not running (SUCCEEDED).
  get_gearing_ratio[session=5]; status=done without error 0.006998 s ago, took 0.545369 s
  messages (4 of 4):
    1762986294.032 Status is now "starting".
    1762986294.032 Status is now "running".
    1762986294.576 Gearing ratio for axis F is: 1.0.
    1762986294.577 Status is now "done".
  other keys in .session: op_code, degraded, data

Here, the agent states that the gearing ratio for axis F is 1, which also
indirectly confirms that the :code:`set_gearing` task was successful.

Examples of `sets` and `gets`
`````````````````````````````
Below are 2 examples of setting and querying a specific state for a Galil axis::

  >>> client.set_motor_state(axis='F', state='disable')
  >>> response = client.get_motor_state(axis='F')
  >>> OCSReply: OK : Operation "get_motor_state" is currently not running (SUCCEEDED).
  get_motor_state[session=3]; status=done without error 0.007853 s ago, took 1.4 s
  messages (4 of 4):
    1762987023.477 Status is now "starting".
    1762987023.477 Status is now "running".
    1762987024.889 Motor F state: off (raw=1)
    1762987024.889 Status is now "done".
  other keys in .session: op_code, degraded, data

Here, :code:`get_motor_state` reports that axis F is disabled. The raw value shown as
:code:`(raw=1)` reflects how the Galil command works internally: the controller
returns a value of 1 when the axis is *off*.

Another set/get example below::

  >>> client.set_torque_limit(axis='E', val=2.0)
  >>> print(client.get_torque_limit(axis='E'))
  >>> OCSReply: OK : Operation "get_torque_limit" is currently not running (SUCCEEDED).
  get_torque_limit[session=4]; status=done without error 0.006350 s ago, took 2.8 s
  messages (4 of 4):
    1762987510.209 Status is now "starting".
    1762987510.209 Status is now "running".
    1762987512.988 Torque limit for axis E is  2.0000.
    1762987512.988 Status is now "done".
  other keys in .session: op_code, degraded, data

Agent API
---------

.. autoclass:: socs.agents.galil_axis.agent.GalilAxisAgent
    :members:
