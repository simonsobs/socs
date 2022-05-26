.. highlight:: rst

.. _sorenson_dlm:

==================
Sorenson DLM Agent
==================

The Sorenson DLM is a 300V/2A single channel power supply, with over-voltage
protection. The DLM agent communicates with the power supply, reading out
voltage and current values, and defines tasks used to set voltages and
currents.

.. argparse::
   :module: ../agents/sorenson_dlm/dlm_agent.py
   :func: make_parser
   :prog: dlm_agent.py



Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::
      {'agent-class': 'DLMAgent',
        'instance-id': 'dlm',
        'arguments' :[['--ip-address', '10.10.10.21'],
                      ['--mode', 'acq'],
                      ['--port', '9221'],]},

Docker Compose
``````````````

An example docker-compose configuration::
  ocs-dlm:
    image: simonsobs/ocs-dlm-agent:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    command:
      - "--instance-id=dlm"


Description
-----------

The Sorenson DLM is a power supply; depending on the model you own, the voltage
and current limits will differ. In order to apply an output voltage, the DLM
requires both an output voltage value and an output current value. You can also
set an upper-bound on the voltage output for safety purposees (overvoltage
setting).


Agent API
---------


.. autoclass:: agents.sorenson_dlm.dlm_agent.DLMAgent
    :members:

Example Clients
---------------
The following client sets the output voltage and current to 1V and 1A, respectively::

        from ocs.ocs_client import OCSClient

        client = OCSClient('dlm')

        #Stop data acquisition
        client.close()

        #Set overvoltage protection
        client.set_over_volt(over_volt=1.)
        #Set DLM Voltage
        client.set_voltage(voltage = 1.)
        client.set_current(current = 1.)

        #Re-start data acq
        client.acq.start()
