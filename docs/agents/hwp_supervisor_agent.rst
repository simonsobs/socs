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
which monitors HWP-related processes to compile full state info for the HWP, and uses
that to make a determination if the HWP should be shutdown.

For high-level control, the HWP supervisor implements a state machine that
is used to perform complex operations with HWP agents that depend on the global
state of the HWP and related hardware.

Control States and Actions
`````````````````````````````
In the context of the HWP supervisor state machine, a *Control State* is a python
dataclass that contains data to dictate what the supervisor will do on each
update call. For example, while in the ``WaitForTargetFreq`` state, the
supervisor will do nothing until the HWP frequency is within tolerance of a
specified freq for a specified period of time, at which point it will transition
into the Done state.

A *Control Action* is a user-requested operation, in which a starting control
state is requested, that then transitions through any number of subsequent
states before completing. The action object contains its current state, state
history, completion status, and whether it considers itself successful. The
action is considered "complete" when it transitions into a "completion state",
which can be ``Done``, ``Error``, ``Abort``, or ``Idle``, at which point no more
state transitions will occur.  In between update calls, a control action may be
aborted by the state-machine, where the action will transition into the
completed "Abort" state, and no further action will be taken.

OCS agent operations are generally one-to-one with control actions, where each
operation begins a new action, and sleeps until that action is complete.
If an operation is started while there is already an action is in progress, the
current action will be aborted at the next opportunity and replaced with the new
requested action.  The ``abort_action`` task can be used to abort the current
action without beginning a new one.

Examples
```````````
Below is an example client script that runs the PID to freq operation, and waits
until the target freq has been reached.

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

Below is an example of a client script that starts to PID the HWP to 2 Hz, then
aborts the PID action, and shuts off the PMX power supply. Note that the
``abort_action`` here is technically redundant, since starting the new action
would abort the active action in the same manner.

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

.. autoclass:: socs.agents.hwp_supervisor.agent.ControlAction
    :members:

.. autoclass:: socs.agents.hwp_supervisor.agent.HWPSupervisor
    :members:

.. autoclass:: socs.agents.hwp_supervisor.agent.get_op_data
