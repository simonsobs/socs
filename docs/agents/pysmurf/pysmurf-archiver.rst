.. highlight:: rst

.. _pysmurf_archiver:

====================
Pysmurf Archiver
====================

The Pysmurf Archiver agent actively monitors the ``pysmurf_files`` database,
and copies newly registered files to their new archived path on the storage
node.

.. argparse::
    :filename: ../agents/pysmurf_archiver/pysmurf_archiver_agent.py
    :func: make_parser
    :prog: python3 pysmurf_archiver_agent.py

Dependencies
------------

In addition to the dependencies listed in the Pysmurf Archiver's
``requirements.txt`` file, the Archiver needs ssh-keys configured to be able to
rsync files off of the smurf server.

Setting up SSH Permissions
``````````````````````````
For instructions on how to setup ssh-permissions for the pysmurf-archiver,
see the following SO-wiki page: http://simonsobservatory.wikidot.com/daq:smurf-ssh-permissions

Configuration File Examples
-----------------------------

OCS Site Config
````````````````

Example site-config entry::

    {'agent-class': 'PysmurfArchiverAgent',
     'instance-id': 'pysmurf-archiver',
     'arguments': [['--data-dir', '/data/pysmurf/'],
                   ['--host', 'data@smurf-srv'],
                   ['--mode', 'run'],
                   ['--target', 'pysmurf-monitor']]},

Docker Compose
````````````````
The docker-compose entry is similar to that of the pysmurf-monitor. For example::

    ocs-pysmurf-archiver:
        image: simonsobs/ocs-pysmurf-archiver-agent:${SOCS_TAG}
        user: "9000"    # ocs user id
        container_name: ocs-pysmurf-archiver
        environment:
            MYSQL_HOST: ${DB_HOST}
            MYSQL_DATABASE: ${DB}
            MYSQL_USER: ${DB_USER}
            MYSQL_PASSWORD: ${DB_PW}
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /home/ocs:/home/ocs
            - /data:/data

Description
-----------

The archiver's role is to copy files from from the smurf-server over to a
storage node. It does this by continuously monitoring the pysmurf_files
database, and finding any uncopied files writen by the target specified in the
site args.

It then rsync's the files over to a new location on the storage node,
setting ``copied=1`` if successful, and incrementing the failure counter if
unsuccessful. 

There is a single **run** process that continuously checks the database
for new files. This is automatically started when the agent boots and shouldn't
stop unless something breaks.


Archived Path
``````````````

The archiver uses the ``action`` and ``action_timestamp`` fields so that
plots and outputs that are created during a single user action are archived
together. Action names for pysmurf and sodetlib functions are generally the
top-level function name that the user runs, but actions can also be set at
runtime with the keyword argument ``pub_action``.

The archived path is determined by::

    <data_dir>/<5 ctime digits>/<pub_id>/<action_timestamp>_<action>/<plots or outputs>

Where ``<data_dir>`` is the ocs-site argument for the archiver, the 5 ctime
digits corresponds with ~ 1 day of data, and ``<pub_id>`` is the pysmurf
publisher id.
For instance, if a user runs ``S.tracking_setup`` at ``ctime`` 1589517264,
on crate=1, slot=2, the output might be stored in the directory::

    <data_dir>/15895/crate1_slot2/1589517264_tracking_setup/outputs

.. autofunction:: agents.pysmurf_archiver.pysmurf_archiver_agent.create_local_path


Agent API
----------
.. autoclass:: agents.pysmurf_archiver.pysmurf_archiver_agent.PysmurfArchiverAgent
    :members:
