Simons Observatory Control System
=================================

The Simons Observatory Control System (SOCS) repository contains SO specific
OCS code. This includes OCS Agents designed for interfacing with SO specific
hardware, as well as SO specific configuration recommendations. For information
about general OCS components, see the `OCS Documentation
<https://ocs.readthedocs.io/en/latest/?badge=latest>`_.

Contents
========

===================  ============================================================
Section              Description
===================  ============================================================
User Guide           Start here for information about the design and use of SOCS.
Agent Reference      Details on configuration and use of the OCS Agents
                     provided by SOCS.
Simulator Reference  Simulators are used to mock software and hardware
                     interfaces when access to actual hardware is unavailable.
                     These are useful for testing other code.
Developer Guide      Information relevant to developers who are contributing to
                     SOCS.
API Reference        Full API documentation for core parts of the SOCS library.
===================  ============================================================

.. toctree::
    :caption: User Guide
    :maxdepth: 2

    user/intro
    user/installation
    user/webserver
    user/sequencer

.. toctree::
    :caption: Agent Reference
    :maxdepth: 2

    agents/acu_agent
    agents/bluefors_agent
    agents/chwp_encoder
    agents/cryomech_cpa
    agents/fts_agent
    agents/hwp_picoscope
    agents/hwp_rotation_agent
    agents/holo_fpga
    agents/holo_synth
    agents/ibootbar
    agents/labjack
    agents/lakeshore240
    agents/lakeshore336
    agents/lakeshore370
    agents/lakeshore372
    agents/lakeshore425
    agents/latrt_xy_stage
    agents/magpie
    agents/meinberg_m1000_agent
    agents/pfeiffer
    agents/pfeiffer_tc400
    agents/pysmurf-controller
    agents/pysmurf-monitor
    agents/scpi_psu
    agents/smurf_crate_monitor
    agents/suprsync
    agents/synacc
    agents/tektronix3021c
    agents/thorlabs_mc2000b
    agents/vantage_pro2
    agents/wiregrid_actuator
    agents/wiregrid_encoder
    agents/wiregrid_kikusui

.. toctree::
    :caption: Simulator Reference
    :maxdepth: 2

    simulators/ls240_simulator
    simulators/ls372_simulator
    agents/smurf_file_emulator
    simulators/smurf_stream_simulator

.. toctree::
    :caption: Developer Guide
    :maxdepth: 2

    developer/snmp
    developer/testing

.. toctree::
    :caption: API Reference
    :maxdepth: 2

    api

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
