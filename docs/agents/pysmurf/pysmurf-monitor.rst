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
An example docker-compose entry might look like::

    ocs-pysmurf-monitor:
        image: simonsobs/ocs-pysmurf-monitor-agent:${SOCS_TAG}
        hostname: ocs-docker
        user: cryo:smurf
        network_mode: host
        container_name: ocs-pysmurf-monitor
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
        command:
            - "--site-hub=ws://${CB_HOST}:8001/ws"
            - "--site-http=http://${CB_HOST}:8001/call"

Where SOCS_TAG and CB_HOST are set in the ``.env`` file in the same dir as the
docker-compose file.

Description
-----------

.. _pysmurf_monitor_suprsync_db:

Interfacing with the SupRsync Database
````````````````````````````````````````
The pysmurf-monitor agent now adds files
to a specified suprsync database when a new pysmurf file is registered, or it
receives a message from the publisher built into the smurf-streamer saying that
a g3 file has been closed and finalized.

Pysmurf auxiliary files will be written using the archive name "smurf",
and g3 timestreams will have the archive name "timestreams". The
pysmurf-monitor will determine the remote relative path based on the pysmurf
action / action timestamp, so it will conform to the directory structure
previously used by the pysmurf archiver::

    <remote_base_dir>/<5 ctime digits>/<pub_id>/<action_timestamp>_<action>/<plots or outputs>

The SupRsync agents on the smurf-server will use these database entries to know
what files to copy over to a daq node or simons1.


Agent API
---------

.. autoclass:: agents.pysmurf_monitor.pysmurf_monitor.PysmurfMonitor
    :members:
    :exclude-members: datagramReceived

Supporting APIs
---------------
.. automethod:: agents.pysmurf_monitor.pysmurf_monitor.create_remote_path

.. automethod:: agents.pysmurf_monitor.pysmurf_monitor.PysmurfMonitor.datagramReceived
