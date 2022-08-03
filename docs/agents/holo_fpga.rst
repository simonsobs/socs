.. highlight:: rst

.. _holo_fpga_agent:

========================
Holography FPGA Agent
========================

The Holography FPGA Agent is provided with OCS to help demonstrate and debug issues with the holography ROACH2 FPGA.
It will connect the computer to the ROACH via an ethernet port, take data, and pass it to the OCS feed.

.. argparse::
   :module: agents.holo_fpga.roach_agent
   :func: make_parser
   :prog: roach_agent.py

Dependencies
------------

Python Packages:
- casperfpga (https://pypi.org/project/casperfpga/)
- holo_daq (https://github.com/McMahonCosmologyGroup/holog_daq)

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file.

OCS Site Config
````````````````

To configure the Holography FPGA Agent we need to add a FPGAAgent block to our
ocs configuration file. Here is an example configuration block using all of the
available arguments::

      {'agent-class': "FPGAAgent",
       'instance-id' : 'fpga',
        'arguments': [['--config_file','holog_config.yaml']]},

Description
-----------

The FPGAAgent contains functions which control the FPGA for holography measurements.  Before the FPGA can take measuremnts, the user needs to initialize the FPGA using the init_FPGA() function.  This will connect to the FPGA via an ethernet port (user specified in the holog_config.yaml file) and programs the FPGA using a .fpg file.

Once the FPGA is initialized, the user can take data using the take_data() function.  This will record the cross-correlations A, BB, AB, and phase.

Agent API
---------

.. autoclass:: agents.holo_fpga.roach_agent.FPGAAgent
    :members:

Example Clients
---------------

To initialize the ROACH2 FPGA, use the "fpga" agent::

    from ocs.ocs_client import OCSClient
    agent_fpga = OCSClient("fpga")
    agent_fpga.init_FPGA()

Example Config File
-------------------

roach: "192.168.4.20"
ghz_to_mhz: 1000
N_MULT: 8
F_OFFSET: 10
baseline: 'bd'