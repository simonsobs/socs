.. highlight:: rst

.. _pysmurf_controller:

====================
Pysmurf Controller
====================

The pysmurf controller runs pysmurf scripts by beginning an external process
that initializes a pysmurf object and calls its functions.
When it exists, the SODET library will be mounted into the docker container so
all SODET scripts will be accessible. Currently, you will either need to
manually mount a script into the docker container, or put them in the
``OCS_CONFIG_DIR`` which is mounted into every OCS container to ``/config``.

The pysmurf object will publish status and file info over a UDP channel
watched by the pysmurf-monitor. Publish options can be set through environment
variables.

Site Options
------------

.. argparse::
    :filename: ../agents/pysmurf_controller/pysmurf_controller.py
    :func: make_parser
    :prog: python3 pysmurf_controller.py

Example site-config entry::

      {'agent-class': 'PysmurfController',
       'instance-id': 'pysmurf-controller',
       'arguments': [['--monitor-id', 'pysmurf-monitor']]},


Pysmurf Publisher options
.........................

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


Docker Configuration
--------------------

The pysmurf-controller docker is built on the pysmurf base image instead
of the standard socs image.
The pysmurf base docker does not always include the most recent version of
pysmurf, so it is common to mount a local dev branch of the repo into the
docker container to ``/usr/local/src/pysmurf``.


The docker-compose for the pysmurf-controller that publishes to a container
named ``ocs-pysmurf-monitor`` might look something like::

    ocs-pysmurf:
        image: simonsobs/ocs-pysmurf-agent:${SOCS_TAG}
        user: "9000"    # ocs user id
        container_name: ocs-pysmurf-controller
        environment:
            SMURFPUB_BACKEND: udp
            SMURFPUB_ID: pysmurf-s2
            SMURFPUB_UDP_HOST: ocs-pysmurf-monitor
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
            - /path/to/dev/pysmurf/:/usr/local/src/pysmurf
        depends_on:
            - "sisock-crossbar"



Running a Script
-----------------

The **run** task will tell the agent to run a script as an external process.
The run function takes params

- **script**: path to the script (in the docker container)
- **args**: list of command line arguments to pass to the script
- **log**: True if using agent logger, path to log file, or False if you don't
  want to log the script's stdout and stderr messages.

For instance, if I have a script in the location
``$OCS_CONFIG_DIR/scripts/pysmurf/tune.py``, I could run it with the following
OCS client from my host computer::

    from ocs.matched_client import MatchedClient

    controller = MatchedClient('pysmurf-controller', args=[])

    script_path = '/config/scripts/pysmurf/tune.py'
    controller.run.start(script=script_path))

where my ``$OCS_CONFIG_DIR`` is mounted to ``/config`` in the docker.


Passing Session Data
---------------------

Often you might want to take data from your pysmurf-script, and access it from
ocs client script. This is now possible by using the smurf publisher.
If you want to access the location of a smurf datafile,
you can put the following into your pysmurf-script::

    active_channels = S.which_on(0)
    datafile = S.stream_data_on()
    S.pub.publish({
        'datafile': datafile, 'active_channels': active_channels
    }, msgtype='session_data')

Marking the publish call with ``msgtype='session_data'`` will make the
pysmurf-monitor (if it exists) pass this data back to the pysmurf-controller. You can
then view the data from the client by running ``status`` or ``wait`` to check the
session data. For example, if the ``tune.py`` file publishes the datafile variable,
you can run::

    from ocs.matched_client import MatchedClient

    controller = MatchedClient('pysmurf-controller', args=[])

    script_path = '/config/scripts/pysmurf/tune.py'
    controller.run.start(script=script_path))

    ok, msg, sess = controller.run.wait()
    print(sess['data'])

    >> {
        'datafile': '/data/smurf_data/20200316/1584401673/outputs/1584402020.dat',
        'active_channels': [0,1,2,3,4]
    }

You can also use this to communicate pysmurf status info to the client. For
instance you can run::

    S.pub.publish({'status': 'Starting take_stream_data'}, msgtype='session_data')
    datafile = S.take_stream_data(10) # Streams data for 10 seconds
    S.pub.publish({
        'status': 'Finished take_stream_data', 'datafile': datafile
     }, msgtype='session_data')

Then if you inspect the session object returned from ``controller.run.status()``
you'll be able to check whether or not ``take_stream_data`` has finished or not.
This can be extremely helpful to monitor progress in long-running pysmurf
scripts from the ocs-web monitor.

Agent API
---------------

This agent registers the **run**, **abort**, and **tune_squids** tasks.

.. autoclass:: agents.pysmurf_controller.pysmurf_controller.PysmurfController
    :members: run_script, abort_script, tune_squids
