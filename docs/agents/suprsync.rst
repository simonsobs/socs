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
    :filename: ../socs/agents/suprsync/agent.py
    :func: make_parser
    :prog: python3 agent.py

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
           '--delete-local-after', '604800',
           '--max-copy-attempts', '10',
           '--copy-timeout', '60',
           '--cmd-timeout', '5',
           '--suprsync-file-root', '/data/so/suprsync',
           ]},

        {'agent-class': 'SupRsync',
         'instance-id': 'smurf-sync',
         'arguments':[
           '--archive-name', 'smurf',
           '--remote-basedir', '/path/to/base/dir/smurf',
           '--db-path', '/data/so/dbs/suprsync.db',
           '--ssh-host', '<user>@<hostname>',
           '--ssh-key', '<path_to_ssh_key>',
           '--delete-local-after', '604800',
           '--max-copy-attempts', '10',
           '--copy-timeout', '20',
           '--cmd-timeout', '5',
           '--suprsync-file-root', '/data/so/suprsync',
           ]},

.. note::
   Make sure you add the public-key corresponding to the ssh id file you will
   be using to the remote server using the ``ssh-copy-id`` function.

.. note::
   If for some reason the user running the suprsync agent does not have file
   permissions, if the ``--delete-local-after`` param is set the agent will crash
   when trying to delete files. In such an environment, make sure this option
   is not used.

Docker Compose
``````````````

Below is a sample docker compose entry for the SupRsync agents.
Because the data we'll be transfering is owned by the ``cryo:smurf`` user, we
set that as the user of the agent so it has the correct permissions. This is
only possible because the ``cryo:smurf`` user is already built into the
SuprSync docker::

  ocs-timestream-sync:
       image: simonsobs/socs:latest
       hostname: ocs-docker
       user: cryo:smurf
       network_mode: host
       container_name: ocs-timestream-sync
       environment:
           - INSTANCE_ID=timestream-sync
           - SITE_HUB=ws://${CB_HOST}:8001/ws
           - SITE_HTTP=http://${CB_HOST}:8001/call
       volumes:
           - ${OCS_CONFIG_DIR}:/config
           - /data:/data
           - /home/cryo/.ssh:/home/cryo/.ssh

  ocs-smurf-sync:
       image: simonsobs/socs:latest
       hostname: ocs-docker
       user: cryo:smurf
       network_mode: host
       container_name: ocs-smurf-sync
       environment:
           - INSTANCE_ID=smurf-sync
           - SITE_HUB=ws://${CB_HOST}:8001/ws
           - SITE_HTTP=http://${CB_HOST}:8001/call
       volumes:
           - ${OCS_CONFIG_DIR}:/config
           - /data:/data
           - /home/cryo/.ssh:/home/cryo/.ssh

.. note::

   If copying to a remote host from a docker container it is required that the
   corresponding ssh-key is also mounted into the container, and that it
   belongs to the user inside of the container with permission 600. The
   configuration above works because the cryo user in the container is the same
   as the one on the host, so the .ssh directory is already properly
   configured. For instance if using an ocs user in the docker, you may want to
   add a .ssh directory for the ocs user on the host (with correct permissions)
   and mount that directory into the container.


Copying Files
-----------------

The SupRsync agent works by monitoring a table of files to be copied in a
sqlite database. The full table is :ref:`described here<SupRsyncFiles>`,
but importantly it contains information such as the full local path, the
remote path relative to a base directory determined by the SupRsync cfg,
checksumming info, several timestamps, and an "archive" name which is used to
determine which SupRsync agent should manage each file. This makes it possible
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
if none is specified). If the ``--delete-local-after`` option is used, the original
file will be deleted after the specified amount of time.

Interfacing with Smurf
``````````````````````````

The primary use case of this agent is copying files from the smurf-server to a
daq node or simons1. The pysmurf monitor agent now populates the files table
with both pysmurf auxiliary files (using the archive name "smurf") and g3
timestream files (using the archive name "timestreams"), as described in
:ref:`this<pysmurf_monitor_suprsync_db>` section. On the smurf-server
we'll be running one SupRsync agent for each of these two archives.


Timecode Directories
------------------------
For data packaging, file destinations are usually grouped into *timecode
directories*, based on the first 5-digits of the ctime at which the file was
created. Destination paths (or remote_paths in the db) will typically look like::

    <remote_basedir>/<5-digit timecode>/<any-number-of-subdirs>/<filename>

where the remote-basedir is set in the suprsync site config, and everything
after is what is registered as the ``remote_path`` in the suprsync database.

With this schema, it is important to transmit information that will allow
downstream processors to determine whether or not a timecode directory is
complete, as opposed to not copied over yet.

The SupRsync database will now automatically detect the timecode directory of
new files that are added, and will track whether a timecode directory is
*complete* (meaning suprsync expects no new files will be added) and *synced*
(that all files in the timecode directory have been synced).

Once a timecode directory is complete and fully synced, suprsync will write a
finalization file::

    <timestamp>_<archive_name>_<dir timecode>_finalized.yaml

that will contain information about the timecode directory, including the
number of files that this suprsync instance has synced over, the sub-directories
that this suprsync instance has added to, the instance-id of the suprsync agent,
and the finalization time. The directory on the local host that these files will
be written to is set using the ``--suprsync-file-root`` argument, and the
path on the remote host will be automatically generated.

Timecode Dir Completion Requirements
`````````````````````````````````````
A timecode directory will be marked as complete if any of the following are true:

 - There are files in the suprsync archive written to a newer timecode directory
 - ``tc_now - tc_directory > 1``,  or we are roughly 1 day past when the timecode directory ended.

Example
```````````
For example, say we have a suprsync agent running on ``smurf-srv20`` with
instance-id ``smurf-sync-srv20``, with ``suprsync-file-root =
/data/so/suprsync``. Suppose that at timestamp ``1686152766`` this agent detects
that all files in the timecode directory ``16750`` of the ``smurf`` archive have
been successfully synced.  This agent will write the local file::

    /data/so/suprsync/16861/smurf-sync-srv20/1686152766_smurf_16750_finalized.yaml

This file will be synced to the remote path::

    <remote_basedir>/16861/suprsync/smurf-sync-srv20/1686152766_smurf_16750_finalized.yaml

where it can be processed by downstream data packaging software.


Agent API
---------

.. autoclass:: socs.agents.suprsync.agent.SupRsync
    :members:

Supporting APIs
---------------

.. _SupRsyncFiles:

SupRsyncFiles Table
```````````````````

.. autoclass:: socs.db.suprsync.SupRsyncFile
    :members:

.. _SupRsyncFilesManager:

SupRsyncFiles Manager
`````````````````````

.. autoclass:: socs.db.suprsync.SupRsyncFilesManager
    :members:

.. _TimecodeDir:

TimecodeDir Table
```````````````````

.. autoclass:: socs.db.suprsync.TimecodeDir
    :members:
