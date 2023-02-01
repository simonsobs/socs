.. highlight:: rst

.. _holo_synth_agent:

=============================
Holography Synthesizer Agent
=============================

The Holography Synthesizer Agent is provided with OCS to help demonstrate and
debug issues with the holography synthesizers. The synthesizers provide a
signal at a desired frequency for holography measurements. This agent will
connect the computer to the two Local Oscillators (LO's) via USB port,
initialize the LO's, set the frequency of each and pass the frequency to the
OCS feed.

.. argparse::
   :module: socs.agents.holo_synth.agent
   :func: make_parser
   :prog: python3 agent.py

.. _holo_synth_deps:

Dependencies
------------

.. note::
    These dependencies are not automatically installed when you install
    ``socs``. You can manually install them, or follow the instructions below.

    Also note that since this agent is tightly coupled with the
    :ref:`holo_fpga_agent`, the instructions below will pull dependencies
    related to that agent as well.

- `holo_daq <https://github.com/McMahonCosmologyGroup/holog_daq>`_

You can install these by first checking you are running Python 3.8::

    $ python --version
    Python 3.8.13

Then by either installing via pip::

    $ python -m pip install 'holog_daq @ git+https://github.com/McMahonCosmologyGroup/holog_daq.git@main'

Or by cloning the socs repository and using the provided requirements file::

    $ git clone https://github.com/simonsobs/socs.git
    $ python -m pip install -r socs/requirements/holography.txt

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
       'arguments': ['--config_file','holog_config.yaml']}

Holography Config File
``````````````````````

.. code-block:: yaml

    roach: '192.168.4.20'
    ghz_to_mhz: 1000
    N_MULT: 8
    F_OFFSET: 10
    baseline: 'bd'
    path_to_roach_init: "~/Desktop/holog_daq/scripts/upload_fpga_py2.py"
    python2_env: "/opt/anaconda2/bin/python2 "

Description
-----------

The SynthAgent contains functions which control the two synthesizers for
holography measurements. Before the synthesizers can output a frequency, the
user needs to initialize both using the init_synth() function. This will
connect to the 2 synthesizers via 2 USB ports and prepares them to read in the
user-desired frequency as the signal output.

Once the synthesizers are initialized, the user can take set the frequency
output using the set_frequencies() function. This will set the frequency
output of BOTH synthesizers.  The user-specified frequency should be in GHz.

Agent API
---------

.. autoclass:: socs.agents.holo_synth.agent.SynthAgent
    :members:
