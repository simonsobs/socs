.. highlight:: rst

.. _suprsync:

==============
SupRsync Agent
==============

The SupRsync agent keeps a local directory synced with a remote server.
It continuously copies over new files to its destination, verifying the copy
by checking the md5sum and deleting the local files after a specified amount
of time if the local and remote checksums match.

.. argparse::
    :filename: ../agents/suprsync/suprsync.py
    :func: make_parser
    :prog: python3 suprsync.py

Copying Files
-----------------

The SupRsync agent works by monitoring a table of files to be copied in a
sqlite database. The full table is :ref:`described here<SupRsyncFiles>`,
but importantly it contains information such as the full local path, the
remote path relative to a base directory determined by the SupRsync cfg,
checksumming info, several timestamps, and an "archive" name which is used to
determine whic SupRsync agent should manage each file. This makes it possible
for  multiple SupRsync agents to monitor the same db, but write their archives
to different base-directories or remote computers.

.. note:: 

   This agent does not remove empty directories, since I can't think of a
   foolproof way to determine whether or not more files will be written to a
   given directory, and pysmurf output directories will likely have
   unregistered files that stick around even after copied files have been
   removed. I think it's probably best to have a separate cronjob make that
   determination and remove directory husks.

Adding Files to the SupRsyncFiles Database
````````````````````````````````````````````

To add a file to the SupRsync database, you can use the
:ref:`SupRsyncFilesManager` class as follows:

.. code-block:: python

    from socs.db.suprsync import SupRsyncFilesManager

    local_abspath = '/path/to/local/file.g3'
    remote_relpath = 'remote/path/file.g3'
    archive = 'timestreams'
    srfm = SupRsyncFilesManager('/path/to/suprsync.db')
    srfm.add_file(local_abspath, remote_relpath, archive)

The SupRsync agent will then copy the file ``/path/to/local/file.g3`` to 
the ``<remote_basedir>/remote/path/file.g3`` on the remote server (or locally
if none is specified). If the ``--delete-after`` option is used, the original
file will be deleted after the specified amount of time.

Interfacing with Smurf
``````````````````````````

The primary use case of this agent is copying files from the smurf-server to a
daq node or simons1. The pysmurf monitor agent now populates the files table
with both pysmurf auxiliary files (using the archive name "smurf") and g3
timestream files (using the archive name "timestreams"), as described in
:ref:`this<pysmurf_monitor_suprsync_db>` section. On the smurf-server
we'll be running one SupRsync agent for each of these two archives.

Configuration File Examples
---------------------------
Below is an example of what the SupRsync configuration might look like on a
smurf-server, with an instance copying g3 files and an instance copying smurf
auxiliary files.

OCS Site Config
```````````````
Below is an example configuration that copies files to the base directory
``/path/to/base/dir`` on a remote system. This will delete successfully
transferred files after 7 days, or 604800 seconds::

        {'agent-class': 'SupRsync',
         'instance-id': 'timestream-sync',
         'arguments':[
           '--archive-name', 'timestreams',
           '--remote-basedir', '/path/to/base/dir/timestreams',
           '--db-path', '/data/so/dbs/suprsync.db',
           '--ssh-host', '<user>@<hostname>',
           '--ssh-key', '<path_to_ssh_key>',
           '--delete-after', '604800', 
           '--max-copy-attempts', '10',
           '--copy-timeout', '60',
           '--cmd-timeout', '5'
           '--timeout-wait', '20'
           ]},

        {'agent-class': 'SupRsync',
         'instance-id': 'smurf-sync',
         'arguments':[
           '--archive-name', 'smurf',
           '--remote-basedir', '/path/to/base/dir/smurf',
           '--db-path', '/data/so/dbs/suprsync.db',
           '--ssh-host', '<user>@<hostname>',
           '--ssh-key', '<path_to_ssh_key>',
           '--delete-after', '604800', 
           '--max-copy-attempts', '10',
           '--copy-timeout', '20',
           '--cmd-timeout', '5'
           '--timeout-wait', '20'
           ]},

.. note::
   Make sure you add the public-key corresponding to the ssh id file you will
   be using to the remote server using the ``ssh-copy-id`` function.

Docker Compose
``````````````

Below is a sample docker-compose entry for the SupRsync agents. 
Because the data we'll be transfering is owned by the ``cryo:smurf`` user, we
set that as the user of the agent so it has the correct permissions. This is
only possible because the ``cryo:smurf`` user is already built into the
SuprSync docker::

  ocs-timestream-sync:
       image: simonsobs/ocs-suprsync-agent:latest
       hostname: ocs-docker 
       user: cryo:smurf
       network_mode: host
       container_name: ocs-timestream-sync
       volumes:
           - ${OCS_CONFIG_DIR}:/config
           - /data:/data
           - /home/cryo/.ssh:/home/cryo/.ssh
       command:
           - '--instance-id=timestream-sync'
           - "--site-hub=ws://${CB_HOST}:8001/ws"
           - "--site-http=http://${CB_HOST}:8001/call"

  ocs-smurf-sync:
       image: simonsobs/ocs-suprsync-agent:latest
       hostname: ocs-docker
       user: cryo:smurf
       network_mode: host
       container_name: ocs-smurf-sync
       volumes:
           - ${OCS_CONFIG_DIR}:/config
           - /data:/data
           - /home/cryo/.ssh:/home/cryo/.ssh
       command:
           - '--instance-id=smurf-sync'
           - "--site-hub=ws://${CB_HOST}:8001/ws"
           - "--site-http=http://${CB_HOST}:8001/call"

.. note::
   If the SSH-key needed to access the remote server is not in the .ssh
   directory, make sure it is being mounted into the docker-container
   and that the ssh-key argument refers to its docker path.


Agent API
---------

.. autoclass:: agents.suprsync.suprsync.SupRsync
    :members:

Supporting APIs
---------------


.. _SupRsyncFiles:

SupRsyncFiles Table
````````````````````````````````
.. autoclass:: socs.db.suprsync.SupRsyncFile
   :members:

.. _SupRsyncFilesManager:

SupRsyncFiles Manager
``````````````````````````````
.. autoclass:: socs.db.suprsync.SupRsyncFilesManager
   :members:
