.. highlight:: rst

.. _acu:

=========
ACU Agent
=========

The Antenna Control Unit (ACU) is an industrial PC with VxWorks installed.
It is used for readout of encoder measurements and control of telescope
platforms.

.. argparse::
    :filename: ../socs/agents/acu/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

.. _acu_deps:

Dependencies
------------
The `soaculib <https://github.com/simonsobs/soaculib>`_ package must be
installed to use this Agent. This can be installed via:

.. code-block:: bash

    $ pip install 'soaculib @ git+https://github.com/simonsobs/soaculib.git@master'

Additionally, ``socs`` should be installed with the ``acu`` group:

.. code-block:: bash

    $ pip install -U socs[acu]

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for soaculib.

OCS Site Config
```````````````

To configure the ACU Agent we need to add a block to the ocs configuration
file. An example configuration block using all availabile arguments is below::

    {'agent-class': 'ACUAgent',
     'instance-id': 'acu-satp1',
     'arguments': [['--acu-config', 'satp1']],
     }

soaculib
````````

The ACU configuration file is parsed by ``soaculib``.  A template is
included within that library; it can be copied into the OCS
configuration area and modified.  ``soaculib`` will use the config
file pointed to by environment variable ``ACU_CONFIG``.  The
``--acu_config`` agent instance argument must correspond to a key in
the ``devices`` section of the ACU configuration file.

Here is an example of a device definition for a SATP::

    'satp1': {
        'base_url': 'http://192.168.1.111:8100',
        'readonly_url': 'http://192.168.1.111:8110',
        'dev_url': 'http://192.168.1.111:8080',
        'interface_ip': '192.168.1.110',
        'streams': {
            'main': {
                'acu_name': 'PositionBroadcast',
                'port': 10004,
                'schema': 'v5'
            },
            'ext': {
                'acu_name': 'PositionBroadcastExt',
                'port': 10005,
                'active': False,
            },
        },

        'platform': 'satp',
        'motion_limits': {
            'azimuth': {
                'lower': -90.0,
                'upper': 450.0,
                'accel': 4.0,
            },
            'elevation': {
                'lower': 18.5,
                'upper': 90.0,
            },
            'boresight': {
                'lower': -55.0,
                'upper': 55.0,
            },
            'axes_sequential': False,
        },

        'ignore_axes': [],

        'named_positions': {
          'home': [180, 60]
        },

        'scan_params': {},

        'sun_avoidance': {},

        'hwp_interlocks': {},

    }


See next section for some details of the configurable parameters.


Configuration Notes
-------------------

Hostnames and port numbers
``````````````````````````

The ``base_url``, ``readonly_url``, and ``dev_url`` should all point
to the IP address of the ACU.  The port numbers refer to different
servers or server configurations and probably don't need to be
altered.

The ``interface_ip`` is the address of the system where the Agent is
running -- this is used to direct UDP frames from the ACU to the
Agent.

Motion limits and restrictions
``````````````````````````````

Settings that affect motion limits, scan parameters, and axis
ignorance:

- ``motion_limits``:

  - Axis limits (``azimuth``, ``elevation``, ``boresight``): These are
    software limits enforced in the Agent.  They are distinct from the
    ACU software limits, and from the hardware limits (enforced by
    limit switches and a PLC).  Generally these will be set equal to,
    or sub-ranges of, the ACU software limits.  Note the identifier
    "boresight" is used for both SATP and the LAT co-rotator.  The
    ``lower`` limit should be numerically less than the ``upper``
    limit.  If specified, the ``accel`` parameter (in deg/s/s) is used
    to limit the minimum turn-around time in ProgramTrack mode.
  - ``axes_sequential``: If True, then (az, el) moves are not
    performed simultaneously.  First one axis is moved, and then the
    next. The Sun Avoidance code is made aware of this restriction and
    optimizes paths with that constraint in mind.

- ``ignore_axes``: If set, should be a list containing any combination
  of "az", "el", "third", and "none".  See further explanation in
  :class:`ACUAgent <socs.agents.acu.agent.ACUAgent>`.
- ``scan_params``: Default scan parameters; currently ``az_speed``
  (float, deg/s) ``az_accel`` (float, deg/s/s), ``el_freq`` (float, Hz),
  and ``turnaround_method`` (str). If not specfied, these are given
  default values depending on the platform type.


Other agent functions
`````````````````````

The ``named_positions`` is a dict mapping a position name
(e.g. "home", "stow") to a list ``[az, el]``.  These are made
available to the ``go_to_named`` task.  Here's an example (in YAML
style):

.. code-block:: yaml

    named_positions:
      home: [180, 60]
      stow: [180, 20]

The ``sun_avoidance`` block controls Sun avoidance parameters, most
importantly the default enable/disable of Sun Avoidance and the
exclusion radius.  Any of the "user-defined policy" parameters can be
included in this block.  Additionally, the key ``enabled`` (boolean)
determines whether active Sun Avoidance is enabled on agent startup.
Here are are some examples:

.. code-block:: yaml

    # Enable Sun avoidance, with 39 deg radius.
    sun_avoidance:
      enabled: true
      exclusion_radius: 39

.. code-block:: yaml

    # Do not enable Sun avoidance by default, but extend the danger
    # zone to 2 hours, for information purposes.
    sun_avoidance:
      enabled: false
      min_sun_time: 7200

When Sun avoidance is configured, but not enabled on startup, it can
be enabled during the run through the
:func:`update_sun <socs.agents.acu.agent.ACUAgent.update_sun>` Task.


Sun Avoidance
-------------

The Sun's position, and the potential danger of the Sun to the
equipment, is monitored and reported by the ``monitor_sun`` Process.
If enabled to do so, this Process can trigger the ``escape_sun_now``
Task, which will cause the platform to move to a Sun-safe position.

The parameters used by an Agent instance for Sun Avoidance are
determined like this:

- Default parameters for each platform (LAT and SATP) are in the Agent
  code.
- On start-up of the Agent, the ACU config file ``sun_avoidance``
  block is parsed, and that modifies the platform default parameters.
- Command-line parameters can modify Sun Safety, through the
  ``--disable-sun-avoidance``, ``--min-el``, and ``--max-el``
  arguments.

The avoidance policy is defined by a few key parameters and concepts;
please see the descriptions of ``sun_dist``, ``sun_time``,
``exclusion_radius``, and more in the :mod:`socs.agents.acu.avoidance`
module documentation.

When Sun Avoidance is active (``active_avoidance`` is ``True``), the
following will be enforced:

- When a user initiates the ``go_to`` Task, the target point of the
  motion will be checked.  If it is not Sun-safe, the Task will exit
  immediately with an error.  If the Task cannot find a set of moves
  that are Sun-safe and that do not violate other requirements
  (azimuth and elevation limits; the ``el_dodging`` policy), then the
  Task will exit with error.  The move may be executed as a series of
  separate legs (e.g. the Task may move first to an intermediate
  elevation, then slew in azimuth, then continue to the final
  elevation) rather than simulataneously commanding az and el motion.
- When a user starts the ``generate_scan`` Process, the sweep of the
  scan will be checked for Sun-safety, and the Process will exit with
  error if it is not.  Furthermore, any movement required prior to
  starting the scan will be checked in the same way as for the
  ``go_to`` Task.
- If the platform, at any time, enters a position that is not
  Sun-safe, then an Escape will be Initiated.  During an Escape, any
  running ``go_to`` or ``generate_scan`` operations will be cancelled,
  and further motions are blocked.  The platform will be driven to a
  position at due North or due South.  The current elevation of the
  platform will be preserved, unless that is not Sun-safe (in which
  case lower elevations will be attempted).  The Escape feature is
  active, even when motions are not in progress, as long as the
  ``monitor_sun`` Process is running.  However -- the Escape operation
  requires that the platform be in Remote operation mode, with no
  persistent faults.

When HWP Interlocks are active (see next section), then HWP state may
affect the elevations available for Sun escape.


HWP Interlocks
--------------

The ACU Agent can be configured to block certain kinds of motion,
depending on the state of the Half-Wave Plate.  When configured, the
ACU will monitor the session data of an HWPSupervisor agent instance
to determine:

- the "grip_state": this can be one of "ungripped", "warm", "cold", or
  "unknown",
- the "spin_state": this can be one of "spinning", "not_spinning",
  "unknown".

These two HWP state strings are used, along with the current elevation
(or the elevation range of a move) to determine whether a given move
should be allowed.

The Agent determines what kinds of moves are permitted by finding
rules in the configuration table that match with the current spin and
grip states, and that also overlap with the required range of
elevation.  If any matching rule grants motion on an axis, then that
is sufficient for the motion to be allowed.

Here is an example ``hwp_interlocks`` configuration block:

.. code-block:: yaml

  hwp_interlocks:
    enabled: true
    limit_sun_avoidance: false
    rules:
    - el_range: [20, 90]
      grip_states: ['warm', 'cold']
      spin_states: ['*']
      allow_moves:
        el: true
        az: true
        third: false
    - el_range: [40, 70]
      grip_states: ['*']
      spin_states: ['*']
      allow_moves:
        el: true
        az: true
        third: false
    - el_range: [40, 70]
      grip_states: ['ungripped']
      spin_states: ['not_spinning']
      allow_moves:
        el: false
        az: false
        third: true

In words, the above example says the following:

- If the elevation is in (40, 70), any az and el moves are permitted,
  regardless of the HWP state.
- In that same elevation range, third axis (boresight) moves are
  permitted only if the HWP is not gripped and not spinning.
- To get down to el of 20 or up to el of 90, you must be in "warm" or
  "cold" gripped states.  In that extended range, you can move in az
  and el freely, even if spin state is not known.
- Ignore these restrictions when a motion needs to be made for Sun
  Avoidance purposes.

If HWP motion constraints should also apply to Sun avoidance
"escapes", then the setting ``limit_sun_avoidance`` should be set to
``true`` (this is the default).  Only the limits associated with
elevation axis motion are considered here -- i.e. the allowed
elevation movement range, for the current HWP state, is used as the
allowable elevation range for escapes.  Sun escape azimuth motion is
not restricted by HWP state.

For more syntax details see :class:`HWPInterlocks
<socs.agents.acu.hwp_iface.HWPInterlocks>`, :class:`MotionRule
<socs.agents.acu.hwp_iface.MotionRule>`.


Exercisor Mode
--------------

The agent can run itself through various motion patterns, using the
Process ``exercise``.  This process is only visible if the agent is
invoked with the ``--exercise-plan`` argument and a path to the
exercise plan config file.  Here is an example config file:

.. code-block:: yaml

  satp1:
    settings:
      use_boresight: false
    steps:
    - type: 'elnod'
      repeat: 2
    - type: 'grid'
      duration: 3600
    - type: 'schedule'
      files:
        - /path/to/schedule1.txt
        - /path/to/schedule2.txt
      duration: 3600
      dwell_time: 600
    - type: 'grease'
      duration: 900

Note that the root level may contain multiple entries; the key
corresponds to the ACU config block name, which would correspond to
the ACU agent ``--acu-config`` argument.

The exercisor writes some diagnostic and timing information to a feed
called ``activity``.

Agent API
---------

.. autoclass:: socs.agents.acu.agent.ACUAgent
    :members:

Example Clients
---------------
Below is an example client demonstrating a go-to task followed by a scan.
Note that all tasks and the generate_scan process can be run while the data
acquisition processes are running::

    from ocs.matched_client import MatchedClient

    def upload_track(scantype, testing, azpts, el, azvel, acc, ntimes):
        acu_client = MatchedClient('acu1')
        acu_client.go_to.start(az=azpts[0], el=el, wait=1)
        acu_client.go_to.wait()
        acu_client.run_specified_scan.start(scantype=scantype, testing=testing, azpts=azpts, el=el, azvel=azvel, acc=acc, ntimes=ntimes)
        acu_client.run_specified_scan.wait()

    if __name__ == '__main__':
        upload_track('linear_turnaround_sameends', True, (120., 160.), 35., 1., 4, 3)

Supporting APIs
---------------

drivers (Scanning support)
``````````````````````````

.. automodule:: socs.agents.acu.drivers
    :members:

avoidance (Sun Avoidance)
`````````````````````````

.. automodule:: socs.agents.acu.avoidance
    :members:

hwp_iface (HWP Interlocks)
``````````````````````````

.. automodule:: socs.agents.acu.hwp_iface
    :members:
