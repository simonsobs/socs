========================================
SOCS - Simons Observatory Control System
========================================

Overview
--------

This repository, `SOCS`_, contains hardware control code for the
Simons Observatory.  This code operates within the framework provided
by `OCS`_.  People who liked OCS and SOCS also liked `Sisock`_, our
time-domain data query system with grafana integration.

.. _`OCS`: https://github.com/simonsobs/ocs/
.. _SOCS: https://github.com/simonsobs/socs/
.. _`SiSock`: https://github.com/simonsobs/sisock/

Installation
------------

This code can be used directly from the source tree.

In order for OCS tools to find these agents, you must add the full
path to the agents directory, e.g. ``/home/simons/code/socs/agents/``,
to your OCS site config file.
