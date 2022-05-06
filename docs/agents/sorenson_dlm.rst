.. highlight:: rst

.. _sorenson_dlm:

==============
Sorenson DLM Agent
==============

# A brief description of the Agent.
The Sorenson DLM is a 300V/2A single channel power supply, with over-voltage
protection. The DLM agent communicates with the power supply, reading out
voltage and current values, and defining tasks used to set voltages and
currents.

.. argparse::
   :module: ../agents/sorenson_dlm/dlm_agent.py
   :func: make_parser
   :prog: dlm_agent.py


Dependencies
------------

# Any external dependencies for agent. Omit if there are none, or they are
# included in the main requirements.txt file.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::
      # DLM Agent
      {'agent-class': 'DLMAgent',
        'instance-id': 'dlm',
        'arguments':[
          ['--ip-address', '10.10.10.21'],
          ['--mode','acq' ],
          ['--port','9221'],]},

Docker Compose
``````````````

An example docker-compose configuration::
  # --------------------------------------------------------------------------
  # OCS - DLM
  # --------------------------------------------------------------------------
  ocs-dlm:
    #<<: *log-options
    image: simonsobs/cs-dlm-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
      - /home/ocs:/home/ocs
    command:
      - "--instance-id=dlm"

Description
-----------

The Sorenson DLM is a power supply; depending on the model you own, the voltage
and current limits will differ. In order to apply an output voltage, the DLM
requires both an output voltage value and an output current value. You can also
set an upper-bound on the voltage output for safety purposees (overvoltage
setting).

Subsection
``````````

# Use subsections where appropriate.

Agent API
---------

# Autoclass the Agent, this is for users to reference when writing clients.

.. autoclass:: agents.dlm.dlm_agent.DLMAgent
    :members:

Example Clients
---------------

# The following client sets the output voltage and current to 1V and 1A, respectively::

        from ocs.matched_client import MatchedClient

        mc = MatchedClient('dlm')

        #Stop data acquisition
        mc.close()

        #Set overvoltage protection
        mc.set_over_volt(over_volt=1.)
        #Set DLM Voltage
        mc.set_voltage(voltage = 1.)
        mc.set_current(current = 1.)

        #Re-start data acq
        mc.acq.start()
