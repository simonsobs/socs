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

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for soaculib.

OCS Site Config
```````````````

To configure the ACU Agent we need to add a block to the ocs configuration
file. An example configuration block using all availabile arguments is below::

    {'agent-class': 'ACUAgent',
     'instance-id': 'acu-satp1',
     'arguments': [['--acu_config', 'satp1']],
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
        },
    }


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

.. automodule:: socs.agents.acu.drivers
    :members:
