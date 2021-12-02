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
Agent Reference      Agents are the OCS components that interface with other
                     systems. These run at all times, awaiting commands from
                     OCS Clients. These are the Agents specifc to SO hardware.
Simulator Reference  Simulators are used to mock software and hardware
                     interfaces when access to actual hardware is unavailable.
                     These are useful for testing other code.
===================  ============================================================

.. toctree::
    :caption: User Guide
    :maxdepth: 2

    user/intro
    user/installation
    user/network
    user/new_agents
    user/webserver

.. toctree::
    :caption: Agent Reference
    :maxdepth: 2

    agents/acu_agent
    agents/bluefors_agent
    agents/chwp_encoder
    agents/cryomech_cpa
    agents/fts_agent
    agents/labjack
    agents/lakeshore240
    agents/lakeshore336
    agents/lakeshore370
    agents/lakeshore372
    agents/latrt_xy_stage
    agents/meinberg_m1000_agent
    agents/pfeiffer
    agents/pysmurf/index
    agents/scpi_psu
    agents/smurf_crate_monitor
    agents/smurf_recorder
    agents/synacc
    agents/tektronix3021c
    agents/vantage_pro2

.. toctree::
    :caption: Simulator Reference
    :maxdepth: 2

    simulators/ls240_simulator
    simulators/ls372_simulator
    simulators/smurf_stream_simulator

.. toctree::
    :caption: Developer Guide
    :maxdepth: 2

    developer/snmp
    developer/testing

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
