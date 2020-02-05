.. highlight:: rst

.. _pysmurf:

====================
Pysmurf/OCS Overview
====================

There are three agents used to interact with `pysmurf <https://github.com/slaclab/pysmurf>`__.
The Pysmurf Controller is used to run pysmurf scripts.
The Pysmurf Monitor listens to pysmurf messages published with the *pysmurf publisher*.
The Pysmurf Archiver copies files pysmurf writes onto a storage node.
There should be one controller per pysmurf instance (per smurf card),
but one pysmurf-monitor and archiver can handle multiple instances.

These pages will show you how to setup these three agents.

.. toctree::
    :caption: Pysmurf agents:
    :maxdepth: 3

    pysmurf-controller
    pysmurf-monitor
    pysmurf-archiver
