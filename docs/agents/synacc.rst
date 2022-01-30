.. highlight:: rst

.. _synacc:

==================
Synaccess Agent
==================
The Synaccess Agent interfaces with the power strip over ethernet to control 
different outlets as well as get their status. 

.. argparse::
    :filename: ../agents/synacc/synacc.py
    :func: make_parser
    :prog: python3 synacc.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Synaccess Agent we need to add a Synaccess Agent block to our ocs 
configuration file. Here is an example configuration block using all of the 
available arguments::

       {'agent-class': 'SynaccessAgent',
        'instance-id': 'synacc',
        'arguments':[
          ['--ip-address', '10.10.10.8'],
          ['--username', 'admin'],
          ['--password', 'admin'],
          ]}

Docker
``````
The Synaccess Agent should be configured to run in a Docker container.
An example docker-compose service configuration is shown here::

  ocs-synacc:
    image: simonsobs/ocs-synaccess-agent
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=synacc"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

Example Client
--------------
Below is an example client to control outlets::

    from ocs import matched_client
    synaccess = matched_client.MatchedClient('synacc', args=[])

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


Agent API
---------

.. autoclass:: agents.synacc.synacc.SynaccessAgent
    :members: get_status, reboot, set_outlet, set_all, start_status_acq
