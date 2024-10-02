.. highlight:: rst

.. _cryomech_cpa:

==================
Cryomech CPA Agent
==================

The Cryomech CPA compressor is a commonly used compressor model for the
pulse tubes within SO. The CPA Agent interfaces with the compressor over
ethernet to monitor the health of the unit, including stats such as Helium
temperature and pressure, oil temperature, and more. The Agent can also
remotely start and stop the compressor.

.. argparse::
    :filename: ../socs/agents/cryomech_cpa/agent.py
    :func: make_parser
    :prog: python3 agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Cryomech CPA Agent we need to add a CryomechCPAAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'CryomechCPAAgent',
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

Docker Compose
``````````````

The Cryomech CPA Agent should be configured to run in a Docker container.
An example docker compose service configuration is shown here::

  ocs-ptc1:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=ptc1
    volumes:
      - ${OCS_CONFIG_DIR}:/config

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Example Clients
---------------

Below is an example client to start data acquisition::

    from ocs.matched_client import MatchedClient

    ptc1 = MatchedClient('ptc1', args=[])

    ptc1.init.start()
    ptc1.init.wait()

    status, msg, session = ptc1.acq.start()

.. note::
    If ``['--mode', 'acq']`` is specified in the ocs configuration file,
    acquisition will begin automatically upon agent startup, so there may be no
    need to run this client.

Agent API
---------

.. autoclass:: socs.agents.cryomech_cpa.agent.PTCAgent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.cryomech_cpa.agent.PTC
    :members:
