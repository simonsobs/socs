========================================
SOCS - Simons Observatory Control System
========================================

.. image:: https://img.shields.io/github/workflow/status/simonsobs/socs/Build%20Develop%20Images
    :target: https://github.com/simonsobs/socs/actions?query=workflow%3A%22Build+Develop+Images%22
    :alt: GitHub Workflow Status

.. image:: https://readthedocs.org/projects/socs/badge/?version=develop
    :target: https://socs.readthedocs.io/en/develop/?badge=develop
    :alt: Documentation Status

.. image:: https://coveralls.io/repos/github/simonsobs/socs/badge.svg?branch=develop
    :target: https://coveralls.io/github/simonsobs/socs?branch=develop

.. image:: https://img.shields.io/badge/dockerhub-latest-blue
    :target: https://hub.docker.com/r/simonsobs/ocs/tags

.. image:: https://img.shields.io/pypi/v/socs
   :target: https://pypi.org/project/socs/
   :alt: PyPI Package

.. image:: https://results.pre-commit.ci/badge/github/simonsobs/socs/develop.svg
   :target: https://results.pre-commit.ci/latest/github/simonsobs/socs/develop
   :alt: pre-commit.ci status

Overview
--------

This repository, `SOCS`_, contains hardware control code for the
Simons Observatory.  This code operates within the framework provided
by `OCS`_.

.. _`OCS`: https://github.com/simonsobs/ocs/
.. _SOCS: https://github.com/simonsobs/socs/

Installation
------------

Install and update with pip::

    $ pip3 install -U socs

If you need to install the optional so3g module you can do so via::

    $ pip3 install -U socs[so3g]

Installing from Source
``````````````````````

If you are considering contributing to SOCS, or would like to use the
development branch, you will want to install from source. To do so,
clone the repository and install using pip:

.. code-block:: bash

    git clone https://github.com/simonsobs/socs.git
    cd socs/
    pip3 install -r requirements.txt
    pip3 install .

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

.. _`ocs docs`: https://ocs.readthedocs.io/en/develop/developer/site_config.html

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
The SOCS documentation can be built using Sphinx. There is a separate
``requirements.txt`` file in the ``docs/`` directory to install Sphinx and any
additional documentation dependencies::

  cd docs/
  pip3 install -r requirements.txt
  make html

You can then open ``docs/_build/html/index.html`` in your preferred web
browser. You can also find a copy hosted on `Read the Docs`_.

.. _Read the Docs: https://socs.readthedocs.io/en/latest/

Tests
-----
The tests for SOCS are run using pytest, and should be run from the
``tests/`` directory::

  $ cd tests/
  $ python3 -m pytest --cov

For more details see `tests/README.rst <tests_>`_.

.. _tests: https://github.com/simonsobs/socs/blob/master/tests/README.rst

Contributing
------------
For guidelines on how to contribute to OCS see `CONTRIBUTING.rst`_.

.. _CONTRIBUTING.rst: https://github.com/simonsobs/socs/blob/master/CONTRIBUTING.rst

License
--------
This project is licensed under the BSD 2-Clause License - see the
`LICENSE.txt`_ file for details.

.. _LICENSE.txt: https://github.com/simonsobs/socs/blob/master/LICENSE.txt
