.. highlight:: rst

.. _ibbn20:

====================
iBB-N20 Agent
====================

The ibbn20 Agent is an OCS Agent which monitors and sends commands to the iBB-N20.
Monitoring and commanding is performed via Telnet.

.. argparse::
    :filename: ../socs/agents/ibb_n20/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the ibbn20 Agent we need to add a ibbn20 Agent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

      {'agent-class': 'ibbn20Agent',
       'instance-id': 'ibbn20',
       'arguments': [['--ip', '10.10.10.50'],
                     ['--port', 23],
                     ['--verbose']]},

Docker Compose
``````````````

The ibbn20 Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-ibbn20:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=ibbn20
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
-----------

The iBB-N20 will be used to power various components. The ibbn20 Agent allows
the monitoring and commanding of the iBB-N20. It monitors the state of each
outlet and the total current. It can set the state of each outlet and cycle
each outlet. The iBB-N20 has a Telnet interface.

Agent API
---------

.. autoclass:: socs.agents.ibb_n20.agent.ibbn20Agent
    :members:

Example Clients
---------------

Below is an example client to control outlets::

    from ocs.ocs_client import OCSClient
    client = OCSClient('ibbn20')

    # Turn outlet on/off/cycle
    client.set_outlet(outlet=1, state='on')
    client.set_outlet(outlet=1, state='off')
    client.set_outlet(outlet=1, state='cycle')
