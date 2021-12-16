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

A SupRsync instance is responsible for copying files to a "base-dir" on a
remote server.

Each SupRsync instance is responsible for managing one "base-dir" on a
remote server.

Each SupRsync instance is in charge of copying files to a single "archive"


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````
Below is an example configuration that copies files to the base directory
``/path/to/base/dir`` on a remote system. This will delete successfully
transferred files after 7 days, or 604800 seconds::

        {'agent-class': 'SupRsync',
         'instance-id': 'timestream-sync',
         'arguments':[
           '--archive-name', 'timestreams',
           '--remote-basedir', '/path/to/base/dir',
           '--db-path', '/data/so/dbs/suprsync.db',
           '--ssh-host', '<user>@<hostname>',
           '--ssh-key', '<path_to_ssh_key>',
           '--delete-after', '604800', 
           '--max-copy-attempts', '10',
           ]},

.. note::
   Make sure you add the public-key corresponding to the ssh id file you will
   be using to the remote server using the ``ssh-copy-id`` function.

Docker Compose
``````````````

Below is a sample docker-compose entry for a SupRsync agent. In most of our
use cases this will be running on the smurf-server, so this will go in with
the smurf-streamer and other smurf software. Because the data we'll be transfering
is owned by the ``cryo:smurf`` user, we set that as the user of the agent so it
has the correct permissions. This is only possible because the ``cryo:smurf``
user is already built into the SuprSync docker::

  ocs-timestream-sync:                                                                             
       image: ocs-suprsync-agent:latest                                                            
       hostname: ocs-docker                                                                        
       user: cryo:smurf                                                                            
       network_mode: host                                                                          
       container_name: ocs-timestream-sync                                                         
       volumes:                                                                                    
           - ${OCS_CONFIG_DIR}:/config                                                             
           - /data:/data                                                                           
       command:                                                                                    
           - '--instance-id=timestream-sync'                                                       
           - "--site-hub=ws://${CB_HOST}:8001/ws"                                                  
           - "--site-http=http://${CB_HOST}:8001/call"                                             


Example Clients
---------------
Since labjack functionality is currently limited to acquiring data, which can 
enabled on startup, users are likely to rarely need a client. This example
shows the basic acquisition functionality:

.. code-block:: python

    # Initialize the labjack
    from ocs import matched_client
    lj = matched_client.MatchedClient('labjack')
    lj.init_labjack.start()
    lj.init_labjack.wait()

    # Start data acquisiton
    status, msg, session = lj.acq.start(sampling_frequency=10)
    print(session)

    # Get the current data values 1 second after starting acquistion
    import time
    time.sleep(1)
    status, message, session = lj.acq.status()
    print(session["data"])

    # Stop acqusition
    lj.acq.stop()
    lj.acq.wait()


Agent API
---------

.. autoclass:: agents.labjack.labjack_agent.LabJackAgent
    :members:

Supporting APIs
---------------

SupRsyncFiles Table
````````````````````````````````
.. autoclass:: socs.db.suprsync.SupRsyncFile
   :members:

SupRsyncFiles Manager
``````````````````````````````
.. autoclass:: socs.db.suprsync.SupRsyncFilesManager
   :members:
