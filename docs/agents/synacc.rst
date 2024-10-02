.. highlight:: rst

.. _synacc:

==================
Synaccess Agent
==================
The Synaccess Agent interfaces with the power strip over ethernet to control
different outlets as well as get their status.

.. argparse::
    :filename: ../socs/agents/synacc/agent.py
    :func: make_parser
    :prog: python3 agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Synaccess Agent we need to add a Synaccess Agent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

       {'agent-class': 'SynaccessAgent',
        'instance-id': 'synacc',
        'arguments':[
          ['--ip-address', '10.10.10.8'],
          ['--username', 'admin'],
          ['--password', 'admin'],
          ['--outlet-names', ['outlet1', 'outlet2', 'outlet3', 'outlet4', 'outlet5']]
          ]}

Docker Compose
``````````````

The Synaccess Agent should be configured to run in a Docker container.
An example docker compose service configuration is shown here::

  ocs-synacc:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=synacc
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Agent API
---------

.. autoclass:: socs.agents.synacc.agent.SynaccessAgent
    :members:

Example Clients
---------------
Below is an example client to control outlets::

    from ocs import ocs_client
    synaccess = ocs_client.OCSClient('synacc', args=[])

    #Get status of the strip
    synaccess.get_status.start()
    status, msg, session = synaccess.get_status.wait()
    session['messages']

    #Reboot outlet
    synaccess.reboot.start(outlet=1)
    synaccess.reboot.wait()

    #Turn on/off outlet
    synaccess.set_outlet.start(outlet=1, on=True)
    synaccess.set_outlet.wait()

    #Turn on/off all outlets
    synaccess.set_all.start(on=True)
    synaccess.set_all.wait()
