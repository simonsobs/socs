.. highlight:: rst

.. _cryomech_cpa1114:

======================
Cryomech CPA1114 Agent
======================

The Cryomech CPA1114 compressor is a commonly used compressor model for the
pulse tubes within SO. The CPA1114 Agent interfaces with the compressor over
ethernet to monitor the health of the unit, including stats such as Helium
temperature and pressure, oil temperature, and more. Control is not yet
implemented.

.. argparse::
    :filename: ../agents/cryomech_cpa1114/cryomech_cpa1114_agent.py
    :func: make_parser
    :prog: python3 crypmech_cpa1114_agent.py

Description
-----------

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Cryomech CPA1114 Agent we need to add a CryomechCPA1114Agent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'CryomechCPA1114Agent',
        'instance-id': 'ptc1',
        'arguments':[
          ['--ip-address', '10.10.10.111'],
          ['--serial-number', 'CPA1114W2FNCE-111111A'],
          ['--mode', 'acq'],
          ['--port', 502],
          ]}

A few things to keep in mind. You should assign your compressor a static IP,
you'll need to know that here. Port 502 is the default communication port. You
should not need to change that unless you have reconfigured your compressor.

Docker
``````
The Cryomech CPA1114 Agent should be configured to run in a Docker container.
An example docker-compose service configuration is shown here::

  ocs-ptc1:
    image: simonsobs/ocs-cryomech-cpa1114-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    command:
      - "--instance-id=ptc1"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Example Client
---------------------------
Below is an example client to start data acqusition (currently the only use case)::

    from ocs.matched_client import MatchedClient

    ptc1 = MatchedClient('ptc1', args=[])

    ptc1.init.start()
    ptc1.init.wait()

    status, msg, session = ptc1.acq.start()


Agent API
---------

.. autoclass:: agents.cryomech_cpa1114.cryomech_cpa1114_agent.PTCAgent
    :members: start_acq
