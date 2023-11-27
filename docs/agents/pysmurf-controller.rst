.. highlight:: rst

.. _pysmurf_controller:

====================
Pysmurf Controller
====================

The Pysmurf Controller OCS agent provides an interface to run pysmurf and
sodetlib control scripts on the smurf-server through an OCS client.

.. argparse::
    :filename: ../socs/agents/pysmurf_controller/agent.py
    :func: make_parser
    :prog: python3 agent.py

.. _pysmurf_controller_deps:

Dependencies
------------

The pysmurf controller requires the following packages:

    - `pysmurf <https://github.com/slaclab/pysmurf>`_
    - `sodetlib <https://github.com/simonsobs/sodetlib>`_
    - `sotodlib <https://github.com/simonsobs/sotodlib>`_

These can be installed via pip:

.. code-block:: bash

    $ python -m pip install 'pysmurf @ git+https://github.com/slaclab/pysmurf.git@main'
    $ python -m pip install 'sodetlib @ git+https://github.com/simonsobs/sodetlib.git@master'
    $ python -m pip install 'sotodlib @ git+https://github.com/simonsobs/sotodlib.git@master'

Additionally, ``socs`` should be installed with the ``pysmurf`` group:

.. code-block:: bash

    $ pip install -U socs[pysmurf]

Configuration File Examples
-----------------------------------

For a detailed walkthrough of how to set up the smurf dockers, see the
`smurf-software-setup SO wiki page <http://simonsobservatory.wikidot.com/smurf-software-setup>`_.

OCS Site Config
````````````````
Example site-config entry::

      {'agent-class': 'PysmurfController',
       'instance-id': 'pysmurf-controller-s2',
       'arguments': [['--monitor-id', 'pysmurf-monitor']]},

Docker Compose
```````````````

The pysmurf-controller docker is built on the pysmurf base image instead of the
standard socs image.  The pysmurf base docker does not always include the most
recent version of pysmurf, so it is common to mount a local dev branch of the
repo into the docker container to ``/usr/local/src/pysmurf``. Similarly, we
mount in a development copy of SODETLIB so that we have the most recent version
without having to rebuild this container.


The docker-compose for the pysmurf-controller that publishes to a container
named ``ocs-pysmurf-monitor`` might look something like::

    ocs-pysmurf:
        image: simonsobs/ocs-pysmurf-agent:${SOCS_TAG}
        user: cryo:smurf
        network_mode:  host
        container_name: ocs-pysmurf-controller
        security_opt:
            - "aparmor=docker-smurf"
        environment:
            - INSTANCE_ID=pysmurf-controller-s2
            - SITE_HUB=ws://${CB_HOST}:8001/ws
            - SITE_HTTP=ws://${CB_HOST}:8001/call
            - SMURFPUB_BACKEND=udp
            - SMURFPUB_ID=crate1slot2
            - SMURFPUB_UDP_HOST=ocs-pysmurf-monitor
            - DISPLAY
            - OCS_CONFIG_DIR=/config
            - EPICS_CA_ADDR_LIST=127.255.255.255
            - EPICS_CA_MAX_ARRAY_BYTES=80000000
            - SLOT=2
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
            - /home/cryo/repos/pysmurf/client:/usr/local/src/pysmurf/python/pysmurf/client
            - /home/cryo/repos/sodetlib:/sodetlib

where ``CB_HOST`` and ``SOCS_TAG`` are set as environment variables or in the
``.env`` file.

Pysmurf Publisher Options
""""""""""""""""""""""""""

.. _pysmurf_publisher_opts:

The following options can be set through the use of environment variables.
Note that if ``SMURFPUB_BACKEND`` is not set to "udp", messages will be
discarded instead of published.

 .. list-table::
    :widths: 10 50

    * - SMURFPUB_ID
      - An ID string associated with this system in order to
        disambiguate it from others; e.g. "readout_crate_1".
    * - SMURFPUB_BACKEND
      - A string that selects the backend publishing engine.
        Options are: "null" and "udp".  The null backend is
        the default, and in that case the published messages
        are simply discarded.
    * - SMURFPUB_UDP_HOST
      - the target host for UDP packets.  Defaults to
        localhost.
    * - SMURFPUB_UDP_PORT
      - the target port for UDP packets.  Defaults to
        module DEFAULT_UDP_PORT.

Description
------------

The Pysmurf Controller agent exposes many essential pysmurf and sodetlib
operations so that they can be called using OCS. Tasks and processes will
generate a new local pysmurf and det-config instance, and load in the tunefile
specified in the device cfg. The session object will be saved to the pysmurf
instance as ``S._ocs_session`` so that sodetlib functions can add logs and data
directly.

Additionally, arbitrary SODETLIB scripts can be run as subprocesses using the
``run`` task. Data can still be added to the session by passing it using the
PysmurfPublisher to communicate with pysmurf-monitor agent (see the `Passing
Session Data`_ section for more info).

In order for the Pysmurf instance to accurately represent the smurf state,
we must be careful about not using a second pysmurf instance to modify any
variables while a persistant instance exists. For that reason, the ``run``
function and most tasks are protected by a single lock, preventing you
from running multiple tasks at a time.


Example Clients
----------------

Running a Script
``````````````````

The **run** task will tell the agent to run a script as an external process.
The run function takes params

- **script**: path to the script (in the docker container)
- **args**: list of command line arguments to pass to the script
- **log**: True if using agent logger, path to log file, or False if you don't
  want to log the script's stdout and stderr messages.

For instance, to run a script ``sodetlib/scripts/tune.py``, the client script
would look like::

    from ocs.matched_client import MatchedClient

    controller = MatchedClient('pysmurf-controller-s2', args=[])

    script_path = '/sodetlib/scripts/tune.py'
    args=['--bands', '0', '1', '2']
    controller.run.start(script=script_path, args=args)



Passing Session Data
``````````````````````
The Pysmurf Publisher can be used to pass information back from a detector operation
script to the ocs client script using the ``session_data`` and ``session_logs``
message types.

Below is a simple control script that demonstrates this

.. code-block:: python
   :name: stream_data.py

    active_channels = S.which_on(0)
    S.pub.publish("Starting data stream", msgtype='session_log')
    datafile = S.take_stream_data(10) # Streams data for 10 seconds
    S.pub.publish("Data stream is closed", msgtype='session_log')
    S.pub.publish({'datafile': datafile}, msgtype='session_data')

From the OCS Client you can then inspect the session data

.. code:: python

    from ocs.matched_client import MatchedClient

    controller = MatchedClient('pysmurf-controller-s2', args=[])

    script_path = '/config/scripts/pysmurf/stream.py'
    controller.run.start(script=script_path))

    ok, msg, sess = controller.run.wait()
    print(sess['data'])

This prints the dictionary::

    {
        'datafile': '/data/smurf_data/20200316/1584401673/outputs/1584402020.dat',
        'active_channels': [0,1,2,3,4]
    }

Agent API
---------------
.. autoclass:: socs.agents.pysmurf_controller.agent.PysmurfController
    :members:

Supporting APIs
---------------

.. autoclass:: socs.agents.pysmurf_controller.agent.PysmurfScriptProtocol
    :members:
