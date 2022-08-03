.. highlight:: rst

.. _holo_synth_agent:

=============================
Holography Synthesizer Agent
=============================

The Holography Synthesizer Agent is provided with OCS to help demonstrate and debug issues with the holography synthesizers, which provide a signal at a desired frequency for holography measurements.
It will connect the computer to the two Local Oscillators (LO's) via USB port, initialize the LO's, set the frequency of each and pass the frequency to the OCS feed.

.. argparse::
   :module: agents.holo_synth.synth_agent
   :func: make_parser
   :prog: synth_agent.py

Dependencies
------------

Python Packages:
- holo_daq (https://github.com/McMahonCosmologyGroup/holog_daq)


Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file.

OCS Site Config
````````````````

To configure the Holography FPGA Agent we need to add a FPGAAgent block to our
ocs configuration file. Here is an example configuration block using all of the
available arguments::

      {'agent-class': 'SynthAgent',
       'instance-id': 'synth_lo',
       'arguments': [['--config_file','holog_config.yaml']]}

Description
-----------

The SynthAgent contains functions which control the two synthesizers for holography measurements.  Before the synthesizers can output a frequency, the user needs to initialize both using the init_synth() function.  This will connect to the 2 synthesizers via 2 USB ports and prepares them to read in the user-desired frequency as the signal output.

Once the synthesizers are initialized, the user can take set the frequency output using the set_frequencies() function.  This will set the frequency output of BOTH synthesizers.  The user-specified frequency should be in GHz

Agent API
---------

.. autoclass:: agents.holo_synth.synth_agent.SynthAgent
    :members:

Example Clients
---------------

To initialize the synthesizers, use the "synth_lo" agent::

    from ocs.ocs_client import OCSClient
    client = OCSClient("synth_lo")
    client.init_synth()

Example Config File
-------------------

roach: "192.168.4.20"
ghz_to_mhz: 1000
N_MULT: 8
F_OFFSET: 10
baseline: 'bd'
