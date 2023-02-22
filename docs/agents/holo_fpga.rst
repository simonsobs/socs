.. highlight:: rst

.. _holo_fpga_agent:

========================
Holography FPGA Agent
========================

The Holography FPGA Agent is provided with OCS to help demonstrate and debug
issues with the holography ROACH2 FPGA. It will connect the computer to the
ROACH via an ethernet port, take data, and pass it to the OCS feed.

.. argparse::
   :module: socs.agents.holo_fpga.agent
   :func: make_parser
   :prog: python3 agent.py

.. _holo_fpga_deps:

Dependencies
------------

.. note::
    These dependencies only support Python 3.8! As such, they are not
    automatically installed when you install ``socs``. You can manually install
    them, or follow the instructions below.

- `casperfpga <https://pypi.org/project/casperfpga/>`_
- `holo_daq <https://github.com/McMahonCosmologyGroup/holog_daq>`_

You can install these by first checking you are running Python 3.8::

    $ python --version
    Python 3.8.13

Then by either installing via pip::

    $ python -m pip install 'casperfpga @ git+https://github.com/casper-astro/casperfpga.git@py38'
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

      {'agent-class': 'FPGAAgent',
       'instance-id': 'fpga',
       'arguments': ['--config_file', 'holog_config.yaml']},

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

The FPGAAgent contains functions which control the FPGA for holography
measurements. Before the FPGA can take measuremnts, the user needs to
initialize the FPGA using the init_FPGA() function. This will connect to the
FPGA via an ethernet port (user specified in the holog_config.yaml file) and
programs the FPGA using a .fpg file.

Once the FPGA is initialized, the user can take data using the take_data()
function. This will record the cross-correlations A, BB, AB, and phase.

Agent API
---------

.. autoclass:: socs.agents.holo_fpga.agent.FPGAAgent
    :members:
