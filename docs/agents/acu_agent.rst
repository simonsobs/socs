.. highlight:: rst

.. _acu:

=========
ACU Agent
=========

The Antenna Control Unit (ACU) is an industrial PC with VxWorks installed.    
It is used for readout of encoder measurements and control of telescope
platforms.

.. argparse::
    :filename: ../agents/acu/acu_agent.py
    :func: add_agent_args
    :prog: python3 acu_agent.py

Dependencies
------------
The `soaculib <https://github.com/simonsobs/soaculib>`_ package must be
installed to use this Agent.

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for soaculib.

ocs_config
``````````
To configure the ACU Agent we need to add a block to the ocs configuration
file. An example configuration block using all availabile arguments is below::

    {'agent-class': 'ACUAgent',
     'instance-id': 'acu1',
     'arguments': [['--acu_config', 'guess']],
     }

soaculib
````````
We additionally need to add a block to the soaculib configuration file. An
example configuration block is below::

    ocs-acu-1: {
        'base-url': 'http://192.168.1.109:8100',
        'dev_url': 'http://192.168.1.109:8080',
        'interface_ip': '192.168.1.110',
        'motion_waittime': 5.0,
        'streams': {
            'main': {
                'acu_name': 'PositionBroadcast',
                'port': 10001,
                'schema': 'v1',
                'active': True
            },
            'ext': {
                'acu_name': 'PositionBroadcastExt',
                'port': 10002,
                'schema': 'v1'
                'active': False
            }
        }
    }

Example Client
--------------
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

Agent API
---------

.. autoclass:: agents.acu.acu_agent.ACUAgent
    :members: start_monitor, start_udp_monitor, generate_scan, go_to,
        run_specified_scan, set_boresight, stop_and_clear
