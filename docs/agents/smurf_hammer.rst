.. highlight:: rst

.. _smurf_hammer:

==================
SMuRF Hammer Agent
==================

.. image:: https://img.shields.io/badge/AI-assisted-orange
   :alt: Agent written with AI assistance

The SMuRF Hammer Agent wraps sodetlib's ``jackhammer hammer`` CLI command as an
OCS agent. It operates on the crate controlled by the SMuRF server to which it
is deployed and accepts the usual ``jackhammer`` options. Slots for which the
hammer fails will be reported in the session data. There is also a monitoring
process to expose the configuration state of each slot.

.. argparse::
    :filename: ../socs/agents/smurf_hammer/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Dependencies
--------------

The SMuRF Hammer Agent requires the following packages:

    - `sodetlib <https://github.com/simonsobs/sodetlib>`_

jackhammer requires EPICS to be installed on the host. The easiest
way to do this is to follow the installation steps present in the
`Dockerfile from smurf_docker <https://github.com/simonsobs/smurf_dockers/blob/v0.0.9/smurf_base/Dockerfile>`_
To build that version of EPICS I found I needed to use the following
compiler flags:

.. code-block:: bash

    -std=c++98 -fno-access-control

Note that it is also necessary to set the EPICS environment variables
from the Dockerfile in the host's .bashrc and also the following:

.. code-block:: bash

    EPICS_CA_ADDR_LIST=127.255.255.255
    EPICS_CA_MAX_ARRAY_BYTES=80000000

Additionally, ``socs`` should be installed with the ``pysmurf`` group:

.. code-block:: bash

    $ pip install -U socs[pysmurf]

Configuration File Examples
------------------------------
Below are configuration examples for the ocs config file and for the
docker compose service.

OCS Site Config
`````````````````
Here is an example of an agent configuration block for the ocs-site-config
file::

    {'agent-class': 'SmurfHammerAgent',
     'instance-id': 'smurf-hammer',
     'arguments': []},

To suppress the auto-starting monitor process::

    {'agent-class': 'SmurfHammerAgent',
     'instance-id': 'smurf-hammer',
     'arguments': ['--no-processes']},

Description
--------------

The agent exposes two operations:

**hammer** (task)
    Resets and reconfigures the specified SMuRF slots by calling
    ``sodetlib.hammers.jackhammer.hammer()``. The sequence reboots the
    carriers, waits for EPICS connectivity, and runs pysmurf setup. Failures
    at each stage are caught per-slot, and the remaining slots continue.

**monitor** (process)
    Continuously polls each slot's EPICS registers using ``epics.caget()``
    directly (bypassing pysmurf, so it works even when the system is
    degraded). Two registers are queried per slot every 10 seconds:

    - ``AMCc.SmurfApplication.SystemConfigured`` -- whether pysmurf setup
      has completed.
    - ``AMCc.SmurfApplication.ConfiguringInProgress`` -- whether setup is
      currently running.

    Results are published to the ``system_configured`` OCS feed for HK
    archival and Grafana. The monitor auto-starts on agent launch unless
    ``--no-processes`` is passed.

    Unreachable slots are recorded as ``None`` in session data and ``-1``
    in the feed.

Agent API
-----------
.. autoclass:: socs.agents.smurf_hammer.agent.SmurfHammerAgent
    :members:
