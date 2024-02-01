.. highlight:: rst

.. _hwp_supervisor:

=====================
HWP Supervisor Agent
=====================

The HWP supervisor agent monitors and can issue commands to hwp subsystems,
and monitors data from other agents on the network that may be relevant to HWP
operation.  Session data from the supervisor agent's ``monitor`` task can be
used to trigger shutdown procedures in the HWP subsystems.


.. argparse::
    :filename: ../socs/agents/hwp_supervisor/agent.py
    :func: make_parser
    :prog: python3 agent.py


Configuration File Examples
---------------------------

OCS Site Config
````````````````````

Here is an example of a config block you can add to your ocs site-config file::

       {'agent-class': 'HWPSupervisor',
        'instance-id': 'hwp-supervisor',
        'arguments': [
            '--ybco-lakeshore-id', 'cryo-ls240-lsa2619',
            '--ybco-temp-field', 'Channel_7',
            '--ybco-temp-thresh', 75,
            '--hwp-encoder-id', 'hwp-bbb-e1',
            '--hwp-pmx-id', 'hwp-pmx',
            '--hwp-pid-id', 'hwp-pid',
            '--ups-id', 'power-ups-az',
            '--ups-minutes-remaining-thresh', 45,
            '--iboot-id', 'power-iboot-hwp-2',
            '--iboot-outlets', [1,2]
        ]}


Docker Compose
````````````````

If you want to run this agent in a docker, you can use a configuration like the
one below::

  ocs-hwp-supervisor:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=hwp-supervisor
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Description
--------------

This agent has two main purposes:

- Monitor HWP subsystems and related agents to make high level determinations
  such as when subsystems should start their shutdown procedure
- Serve as a host for high-level HWP operations that require coordinated control
  of various HWP subsystems, such as "Begin rotating at 2 Hz"

For the first point, the supervisor agent implements the ``monitor`` process,
which monitors HWP-related to compile full state info for the HWP, and uses
that to make a determination if the HWP should be shutdown.

For high-level control, the HWP supervisor implements a state machine that
is used to perform complex actions with HWP agents that depend on the global

Running actions
`````````````````
HWP supervisor actions such as ``pid_to_freq``, ``set_const_voltage``,
``brake``, and ``pmx_off`` request that the corresponding is run by the main
``spin_control`` process.  Control tasks like these will sleep until the
corresponding action enters an end- state such as Done, Error, or Abort.

You can run an action and make sure it is complete by running the task and
waiting for it to complete. The session-data that is returned will contain the
encoded action, including the state chain, and whether the action was successful
or not. For example, to spin up to a particular frequency, you can run:

.. code-block:: python

    supervisor = OCSClient("hwp-supervisor")

    result = supervisor.pid_to_freq(target_freq=2.0)
    print(result.session['data']['action'])

    >> {'action_id': 6,
        'completed': True,
        'cur_state': {'class': 'Done', 'msg': None, 'success': True},
        'state_history': [{'class': 'PIDToFreq',
                            'direction': '0',
                            'freq_tol': 0.05,
                            'freq_tol_duration': 10.0,
                            'target_freq': 2.0},
                          {'class': 'WaitForTargetFreq',
                            'freq_tol': 0.05,
                            'freq_tol_duration': 10.0,
                            'freq_within_tol_start': 1706829677.7613404,
                            'target_freq': 2.0},
                      {'class': 'Done', 'msg': None, 'success': True}],
          'success': True}

To stop an action while its running, you can use the ``abort_action`` task, 
which will set the state of the current action to ``Abort``, and put the
supervisor into the Idle state.

.. code-block:: python

    supervisor = OCSClient("hwp-supervisor")

    supervisor.pid_to_freq.start(target_freq=2.0)
    supervisor.abort_action()
    res1 = supervisor.pid_to_freq.wait()
    res2 = supervisor.pmx_off()

    print("Result 1:")
    print(res1.session['data']['action'])
    print("Result 2: ")
    print(res2.session['data']['action'])

    >> 
    Result 1:
    {'action_id': 1,
    'completed': True,
    'cur_state': {'class': 'Abort'},
    'state_history': [{'class': 'PIDToFreq',
                        'direction': '0',
                        'freq_tol': 0.05,
                        'freq_tol_duration': 10.0,
                        'target_freq': 2.0},
                      {'class': 'Abort'}],
    'success': False}
    Result 2: 
    {'action_id': 3,
    'completed': True,
    'cur_state': {'class': 'Done', 'msg': None, 'success': True},
    'state_history': [{'class': 'PmxOff', 'success': True},
                      {'class': 'Done', 'msg': None, 'success': True}],
    'success': True}





Agent API
-----------

.. autoclass:: socs.agents.hwp_supervisor.agent.HWPSupervisor
    :members:

.. autoclass:: socs.agents.hwp_supervisor.agent.get_op_data
