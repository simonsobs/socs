========================================
SOCS - Simons Observatory Control System
========================================

.. image:: https://img.shields.io/github/workflow/status/simonsobs/socs/Build%20Develop%20Images
    :target: https://github.com/simonsobs/socs/actions?query=workflow%3A%22Build+Develop+Images%22
    :alt: GitHub Workflow Status

.. image:: https://readthedocs.org/projects/socs/badge/?version=latest
    :target: https://socs.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

.. image:: https://coveralls.io/repos/github/simonsobs/socs/badge.svg?branch=travis
    :target: https://coveralls.io/github/simonsobs/socs?branch=travis

.. image:: https://img.shields.io/badge/dockerhub-latest-blue
    :target: https://hub.docker.com/r/simonsobs/ocs/tags

Overview
--------

This repository, `SOCS`_, contains hardware control code for the
Simons Observatory.  This code operates within the framework provided
by `OCS`_.

.. _`OCS`: https://github.com/simonsobs/ocs/
.. _SOCS: https://github.com/simonsobs/socs/

Installation
------------

To install SOCS, clone the repository and install with `pip`:

.. code-block:: bash

    git clone https://github.com/simonsobs/socs.git
    cd socs/
    pip3 install -r requirements.txt .

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

Docker Images
-------------
Docker images for SOCS and each Agent are available on `Docker Hub`_. Official
releases will be tagged with their release version, i.e. ``v0.1.0``. These are
only built on release, and the ``latest`` tag will point to the latest of these
released tags. These should be considered stable.

Development images will be tagged with the latest released version tag, the
number of commits ahead of that release, the latest commit hash, and the tag
``-dev``, i.e.  ``v0.0.2-81-g9c10ba6-dev``. These get built on each commit to
the ``develop`` branch, and are useful for testing and development, but should
be considered unstable.

.. _Docker Hub: https://hub.docker.com/u/simonsobs

Documentation
-------------
The SOCS documentation can be built using sphinx once you have performed the
installation::

  cd docs/
  make html

You can then open ``docs/_build/html/index.html`` in your preferred web
browser. You can also find a copy hosted on `Read the Docs`_.

.. _Read the Docs: https://socs.readthedocs.io/en/latest/

Contributing
------------
For guidelines on how to contribute to OCS see `CONTRIBUTING.rst`_.

.. _CONTRIBUTING.rst: CONTRIBUTING.rst

License
--------
This project is licensed under the BSD 2-Clause License - see the 
`LICENSE.txt`_ file for details.

.. _LICENSE.txt: LICENSE.txt
