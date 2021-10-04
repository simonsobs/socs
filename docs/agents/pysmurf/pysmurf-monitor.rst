.. highlight:: rst

.. _pysmurf_monitor:

====================
Pysmurf Monitor
====================

The pysmurf_monitor agent listens to the UDP messages that the
*pysmurf publisher* sends and acts on them. It will add newly registered filse
to the pysmurf_files database, and send session info to pysmurf-controller
agents through an OCS Feed.

.. argparse::
    :filename: ../agents/pysmurf_monitor/pysmurf_monitor.py
    :func: make_parser
    :prog: python3 pysmurf_monitor.py

Configuration File Examples
---------------------------

OCS Site Config
````````````````

Example site-config entry::

      {'agent-class': 'PysmurfMonitor',
       'instance-id': 'pysmurf-monitor',
       'arguments': [['--udp-port', 8200],
                     ['--create-table', True]]},

Docker Compose
````````````````

You can set the sql config info with the environment variables MYSQL_HOST,
MYSQL_DATABASE, MYSQL_USER and MYSQL_PASSWORD.

An example docker-compose entry might look like::

    ocs-pysmurf-monitor:
        image: simonsobs/ocs-pysmurf-monitor-agent:${SOCS_TAG}
        hostname: ocs-docker
        user: ocs:ocs
        network_mode: host
        container_name: ocs-pysmurf-monitor
        environment:
            MYSQL_HOST: ${DB_HOST}
            MYSQL_DATABASE: ${DB}
            MYSQL_USER: ${DB_USER}
            MYSQL_PASSWORD: ${DB_PW}
              - env_files/db.env
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
        command:
            - "--site-hub=ws://${CB_HOST}:8001/ws"
            - "--site-http=http://${CB_HOST}:8001/call"

Where DB_HOST, DB, DB_USER, and DB_PW, SOCS_TAG, and CB_HOST are set in the
``.env`` file in the same dir as the docker-compose file.


Description
-----------

.. _pysmurf_files_db:

Pysmurf Files Database
````````````````````````

The pysmurf_files table is located in a MariaDB docker container, usually on
the daq node with the crossbar docker. The database name is ``files``.

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

Agent API
---------

.. autoclass:: agents.pysmurf_monitor.pysmurf_monitor.PysmurfMonitor
    :members:
    :exclude-members: datagramReceived

Supporting APIs
---------------

.. automethod:: agents.pysmurf_monitor.pysmurf_monitor.PysmurfMonitor.datagramReceived
