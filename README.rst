========================================
SOCS - Simons Observatory Control System
========================================

.. image:: https://travis-ci.com/simonsobs/socs.svg?branch=master
    :target: https://travis-ci.com/simonsobs/socs

.. image:: https://readthedocs.org/projects/socs/badge/?version=latest
    :target: https://socs.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

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
to your OCS site config file. Do so by adding the following under your
configured host if it does not already exist:

.. code-block:: yaml

  # List of additional paths to Agent plugin modules.
  'agent-paths': [
    '/path/to/socs/agents/',
  ],

See the `ocs docs`_ for more details.

.. _`ocs docs`: https://ocs.readthedocs.io/en/latest/site_config.html

License
--------
This project is licensed under the BSD 2-Clause License - see the 
`LICENSE.txt`_ file for details.

.. _LICENSE.txt: LICENSE.txt
