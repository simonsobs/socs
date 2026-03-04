.. highlight:: rst

.. _pfeiffer:


======================
Pfeiffer TPG 366 Agent
======================

The Pfeiffer TPG 366 Controller is a six channel pressure gauge monitor. The
Pfeiffer agent communicates with the Controller module, and reads out
pressure readingss from the six different channels.

.. argparse::
    :filename: ../socs/agents/pfeiffer_tpg366/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevent OCS files and for
running the agent in a docker container.

OCS Site Config
```````````````

To configure the Pfeiffer TPG 366 Agent we need to add a PfeifferAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'PfeifferAgent',
        'instance-id': 'pfeiffer',
        'arguments': [
          ['--ip-address', '10.10.10.20'],
          ['--port', '8000'],
          ['--mode', 'acq'],
          ]}

You should assign a static IP address to Pfeiffer device, and record it here.
In general, the Pfeiffer device will assign port 8000 by default. This should
not need to be changed unless you you specificy the port otherwise.

Docker Compose
``````````````

The Pfeiffer Agent can be run via a Docker container. The following is an
example of what to insest into your institution's docker compose file. ::


  ocs-pfeiffer:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=pfeiffer
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

Agent API
---------

.. autoclass:: socs.agents.pfeiffer_tpg366.agent.PfeifferAgent
    :members:

Example Clients
---------------
Below is an example client to start data acquisition::

    from ocs.ocs_client import OCSClienti
    import time
    pfeiffer = OCSClient("pfeiffer", args=[])
    params = {'auto_acquire': True}
    pfeiffer.acq.start(**params)
    pfeiffer.acq.wait()
    time.sleep(0.05)


.. note::
    If ``['--mode', 'acq']`` is specified in the ocs configuration file,
    acquisition will begin automatically upon agent startup, so there may be no
    need to run this client.
