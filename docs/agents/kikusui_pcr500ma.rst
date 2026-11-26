.. highlight:: rst

.. _kikusui_pcr500ma:

========================
KIKUSUI PCR500MA Agent
========================

.. image:: https://img.shields.io/badge/AI-assisted-orange
   :alt: Agent written with AI assistance

This agent is designed to interface with KIKUSUI's PCR500MA AC power supply.


.. argparse::
    :filename: ../socs/agents/kikusui_pcr500ma/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
`````````````````````

An example site-config-file block::

    {'agent-class': 'PCR500MAAgent',
     'instance-id': 'pcr500ma',
     'arguments': [['--port', 5025],
                   ['--ip-address', '192.168.0.100']]
     },


Docker Compose
``````````````

The PCR Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-pcr500ma:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=pcr500ma
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
--------------

PCR500MA is an AC power supply that can be cotrolled via ethernet.
This power supply will be used to the stimulator heater to raise its temperature.

The device only accepts 10/100BASE communication.
Manual can be found `here <https://manual.kikusui.co.jp/P/PCR_MA_USER_E4.pdf>`_.

Normal Operation
----------------

Use ``ramp_to_voltage(volt_set=50)`` to turn on the output and gradually raise
the voltage, or ``ramp_to_voltage(volt_set=0)`` to gradually lower the voltage
and turn the output off. The Task changes the setting by at most 1 V at a time
and waits at least 7 seconds after each change, including the final step.
Before each change, fresh voltage measurements must be within 1.2 V of both
the current setting and the next setting. Before turning the output off, the
measured voltage must be below 0.2 V.

Each voltage change is verified by an immediate setting readback. A mismatch
stops the Task before settling. Subsequent steps use fresh voltage settings,
so external voltage changes during settling are subject to the same safety
checks.

Output ON/OFF changes are also read back before the Task proceeds.

If the output is already off, the Task first resets the voltage setting to
zero. It then enables the output only if the target is nonzero. This also
recovers an instrument left with a nonzero voltage setting and its output off
without requiring a separate client script.

Acquisition continues during the settling intervals. The Task session reports
the target voltage and the latest readbacks. Other voltage/output control
Tasks are rejected while ramping, even with ``force=True``. Abort the ramp
before issuing a manual command. Aborting, losing communication, or failing a
safety check stops further changes and leaves the last commanded state in
place, rather than abruptly switching an active output off. Inspect fresh
readbacks before deciding how to proceed after a failure.

Expert manual operations remain available through ``set_output`` and
``set_volt_ac``. An immediate voltage change now requires
``set_volt_ac(volt_set=..., force=True)``. The existing voltage checks in
``set_output`` remain in effect unless ``force=True`` is supplied.

Client Migration
----------------

The ``get_output`` and ``get_volt_ac`` Tasks have been removed. Read
``client.acq.status().session['data']['output']`` and
``client.acq.status().session['data']['volt_set']`` instead. ``volt_set`` is
the configured voltage; ``V_AC`` is the measured voltage. Both values are
also published to the ``heater_source`` feed. Check acquisition status,
``degraded``, and the data timestamp when using these readings; they can be
stale if acquisition has stopped or communication has failed. The ramp Task
reads directly from the instrument for its safety checks and does not require
acquisition to be running.

Existing clients that change voltage directly must either migrate to
``ramp_to_voltage`` or explicitly pass ``force=True`` to ``set_volt_ac``.


Agent API
---------

.. autoclass:: socs.agents.kikusui_pcr500ma.agent.PCR500MAAgent
   :members:
Supporting APIs
---------------

.. autoclass:: socs.agents.kikusui_pcr500ma.agent.PCRState
   :members:

.. autoclass:: socs.agents.kikusui_pcr500ma.drivers.PCR500MA
   :members:

.. autoclass:: socs.agents.kikusui_pcr500ma.drivers.PCRCoupling
   :members:
