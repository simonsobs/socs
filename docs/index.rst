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

    agents/bluefors_agent
    agents/cryomech_cpa
    agents/scpi_psu
    agents/labjack
    agents/lakeshore240
    agents/lakeshore372
    agents/pysmurf/index
    agents/smurf_recorder
    agents/pfeiffer

.. toctree::
    :caption: Simulator Reference
    :maxdepth: 2

    simulators/ls240_simulator
    simulators/smurf_stream_simulator

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
