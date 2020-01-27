.. highlight:: rst

.. _pysmurf_archiver:

====================
Pysmurf Archiver
====================

The archiver's role is to copy files from from the smurf-server over to a
storage node. It does this by continuously monitoring the
:ref:`pysmurf_files database <pysmurf_files_db>`, and finding any uncopied files
writen by the target specified in the site args.

It then rsync's the files over to a new location on the storage node,
setting ``copied=1`` if successful, and incrementing the failure counter if
unsuccessful. The current file_path on the storage node is given by
``data_dir/<5 ctime digits>/<file_type>/<file_name>``, but this will be updated
soon.

There is a single **run** process that continuously checks the database
for new files. It is started automatically when the agent boots.

Site Options
------------

.. argparse::
    :filename: ../agents/pysmurf_archiver/pysmurf_archiver_agent.py
    :func: make_parser
    :prog: python3 pysmurf_archiver_agent.py

Example site-config entry::

      {'agent-class': 'PysmurfArchiverAgent',
       'instance-id': 'pysmurf-archiver',
       'arguments': [['--data-dir', '/data/pysmurf'],
                     ['--target', 'pysmurf-monitor']]},


Setting up SSH Permissions
--------------------------
For instructions on how to setup ssh-permissions for the pysmurf-archiver,
see the following SO-wiki page: http://simonsobservatory.wikidot.com/daq:smurf-ssh-permissions

Docker Configuration
--------------------
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
        depends_on:
            - "sisock-crossbar"