.. highlight:: rst

.. _smurf_crate_monitor:

=========================
Smurf Crate Monitor Agent
=========================

The SMuRF readout system uses Advanced Telecommunications Computing Architecture
(ATCA) crates for powering and communicating between boards and the site networking
and timing infrastructure. This Agent monitors the sensors in these ATCA crates.

.. argparse::
    :filename: ../socs/agents/smurf_crate_monitor/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the SMuRF Crate Monitor Agent we need to add a CrateAgent entry
to our site configuration file. Here is an example configuration block using
all of the available arguments::

        {'agent-class': 'CrateAgent',
         'instance-id': 'crate1-monitor',
         'arguments':[
           ['--shm-addr', 'root@192.168.1.2'],
           ['--crate-id', 'crate1'],
           ]},

Both arguments are required to run, the 'shm-addr' argumnent should always
be root as user and then the ip address will depend on your setup of the
shelf manager at your site. The '192.168.1.2' address is the default address
setup during the instructions laid out in the 'smurfsetup' instructions on
the simons wiki for so testing institutions. You should make sure that you
can ssh from the computer the docker container will run on to the shelf
manager directly. Additionally in order to connect through the docker
container you will need to setup ssh keys with the ocs-user following these
steps:

1. Make sure ocs-user has a ssh key generated. See
   http://simonsobservatory.wikidot.com/daq:smurf-ssh-permissions for more info

2. Switch to ocs user using 'sudo su ocs'

3. 'ssh' into the smurf-crate and add ssh host-verification when prompted

4. Copy ocs-user ssh key using 'ssh-copy-id'

You also need to add the ocs-base anchor and mount the home directory of
the ocs-user in your 'docker compose' file, see below for an example.

The second argument, 'crate-id', is just an identifier for your feed names
to distinguish between identical sensors on different crates.

Docker Compose
``````````````

The SMuRF Crate Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-smurf-crate-monitor:
    <<: *ocs-base
    image: simonsobs/socs:latest
    hostname: adaq1-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=crate1-monitor
      - LOGLEVEL=debug
    volumes:
      - ${OCS_CONFIG_DIR}:/config
      - /home/ocs:/home/ocs

An example of the 'ocs-base' anchor is shown here::

  x-ocs-base: &ocs-base
  hostname: adaq1-docker
  user: "9000"
  volumes:
    - ${OCS_CONFIG_DIR}:/config

Description
-----------

The ATCA crates have a small computer on board called a shelf manager which
monitors all of the sensors in the crate including ammeters, and voltmeters for
the power into the crates and into each front and rear module of each active
slot used in the crate. There are also tachometers on each of the crate fans
and various thermometers withing the crate and each of the boards plugged into
the crate which the shelf manager monitors.

There are multiple crate manufacturers but the shelf managers all share the
same set of programming/communication called Pigeon Poing Communication so this
agent should work across multiple crate manufacturers. This agent connects to a
shell terminal of a crate shelf manager over ssh through the python subprocess
package and then runs the command ``clia sensordata`` and parses its output to
identify all of the available sensors then stream and publish them.

Agent API
---------

.. autoclass:: socs.agents.smurf_crate_monitor.agent.SmurfCrateMonitor
    :members:
