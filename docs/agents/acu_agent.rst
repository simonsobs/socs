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

We additionally need to add a block to the soaculib configuration file. An
example configuration block is below::

    'satp1': {
        'base_url': 'http://192.168.1.111:8100',
        'readonly_url': 'http://192.168.1.111:8110',
        'dev_url': 'http://192.168.1.111:8080',
        'interface_ip': '192.168.1.110',
        'motion_waittime': 5.0,
        'streams': {
            'main': {
                'acu_name': 'PositionBroadcast',
                'port': 10004,
                'schema': 'v2'
            },
            'ext': {
                'acu_name': 'PositionBroadcastExt',
                'port': 10005,
                'active': False,
            },
        },
        'status': {
            'status_name': 'Datasets.StatusSATPDetailed8100',
            },

        'platform': 'satp',
        'motion_limits': {
            'azimuth': {
                'lower': -90.0,
                'upper': 480.0,
            },
            'elevation': {
                'lower': 20.0,
                'upper': 50.0,
            },
            'boresight': {
                'lower': 0.0,
                'upper': 360.,
            },
            'acc': (8./1.88),
            'axes_sequential': False,
        },
    }


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
- On start-up the default parameters for platform are modified
  according to any command-line parameters passed in by the user.
- Some parameters can be altered using the command line.

The avoidance policy is defined by a few key parameters and concepts;
please see the descriptions of ``sun_dist``, ``sun_time``,
``exclusion_radius``, and more in the :mod:`socs.agents.acu.avoidance`
module documentation.

The ``exclusion_radius`` can be configured from the Agent command
line, and also through the ``update_sun`` Task.

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
