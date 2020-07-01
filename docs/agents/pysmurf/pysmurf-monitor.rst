.. highlight:: rst

.. _pysmurf_monitor:

====================
Pysmurf Monitor
====================

The pysmurf_monitor agent listens to the UDP messages that the
*pysmurf publisher* sends and acts on them.
Currently, its main job is to wait until the publisher registers a new file
that pysmurf has created, and it puts the file info into a database so that
the file can be copied over by the *archiver* running on the storage node.

This agent has no registered operations.

Site Options
------------

.. argparse::
    :filename: ../agents/pysmurf_monitor/pysmurf_monitor.py
    :func: make_parser
    :prog: python3 pysmurf_monitor.py

Example site-config entry::

      {'agent-class': 'PysmurfMonitor',
       'instance-id': 'pysmurf-monitor',
       'arguments': [['--udp-port', 8200],
                     ['--create-table', True]]},



.. _pysmurf_files_db:

Database
--------


The database is located in a MariaDB docker container running on the crossbar
system. The database name is ``files``, and it is also used to index hk files
written by the hk-aggregator.

The table containing the pysmurf file info is called ``pysmurf_files_v<VERSION>``
where ``VERSION`` is the current iteration of the table.
This version number will increment anytime the table schema is changed, so
we don't lose information about old files.
The pysmurf-monitor agent will create the newest version of the ``pysmurf_files``
table automatically if it does not yet exist, but you can also create and drop this table
outside of OCS using the ``socs.db.pysmurf_files_manager`` module by calling::

    python3 socs/db/pysmurf_files_manager.py create

and entering the db password at the prompt.

Below are the columns that exist in ``pysmurf_files_v1``:

..  list-table:: ``pysmurf_files_v1`` columns
    :widths: 10 10 60

    * - path (required)
      - str
      - Filepath. At first it is the path on the smurf-server, and
        once copied it is the path on the storage node.

    * - action
      - str
      - `Pysmurf action` corresponding to the file. All files with the same
        action will be grouped together once archived.

    * - timestamp
      - datetime
      - Time at which file was written

    * - action_timestamp
      - int
      - unix timestamp corresponding to the start of the pysmurf action.
        This determines how files are grouped once archived.

    * - format
      - str
      - File format. **E.g.** "npy" or "txt"

    * - plot
      - bool
      - True if file is a plot

    * - site
      - str
      - Site name

    * - pub_id
      - str
      - Pysmurf publisher ID. (Set by :ref:`SMURFPUB_ID <pysmurf_publisher_opts>`)

    * - instance_id
      - str
      - Instance id of monitor agent that recorded file.

    * - copied
      - bool
      - True if successfully copied by archiver

    * - failed_copy_attempts
      - int
      - Number of failed copy attempts

    * - md5sum (required)
      - binary
      - md5sum of file

    * - pysmurf_version
      - str
      - version id for pysmurf

    * - socs_version
      - str
      - version id for socs


Docker Configuration
--------------------

You can set the sql config info with the environment variables MYSQL_HOST,
MYSQL_DATABASE, MYSQL_USER and MYSQL_PASSWORD.

An example docker-compose entry might look like::

    ocs-pysmurf-monitor:
        image: simonsobs/ocs-pysmurf-monitor-agent:${SOCS_TAG}
        user: "9000"    # ocs user id
        container_name: ocs-pysmurf-monitor
        environment:
            MYSQL_HOST: ${DB_HOST}
            MYSQL_DATABASE: ${DB}
            MYSQL_USER: ${DB_USER}
            MYSQL_PASSWORD: ${DB_PW}
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
        depends_on:
            - "sisock-crossbar"

Where DB_HOST, DB, DB_USER, and DB_PW are set in the ``.env`` file in the same dir as
the docker-compose file.