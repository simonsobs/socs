.. highlight:: rst

.. _magpie:

===============
Magpie Agent
===============

The magpie is an incredibly intelligent bird, with a decent ability to mimic
other bird calls, though not as good as `the superb lyrebird
<https://www.youtube.com/watch?v=mSB71jNq-yQ>`_. In the context of OCS, the job
of the Magpie agent is to take detector data from the SMuRF Streamer and
translate into G3Frames that are compatible with lyrebird. This requires
a small bit of pre-processing and downsampling that is done whenever a new
frame is received. 

.. argparse::
   :filename: ../agents/magpie/magpie_agent.py
   :func: make_parser
   :prog: python3 magpie_agent.py

Configuration File Examples
------------------------------

Below are example docker-compose and ocs configuration files for running the
magpie agent.

Site Config
````````````
Below is the site-config entry for the magpie instance we have running at UCSD
on K2SO. We are displaying detectors using a wafer layout, determined by
a tune map csv file, with a target sample rate of 20 Hz::

      {'agent-class': 'MagpieAgent',
       'instance-id': 'magpie-crate1slot2',
       'arguments': [
         '--stream-id', 'crate1-slot2',

         '--src', 'tcp://localhost:4532',

         '--dest', 8675,
         '--delay', 5,
         '--target-rate', 20
         '--layout', 'wafer',

         # Detmap CSV file
         '--csv-file', '/home/jlashner/lyrebird_demo/detmap.csv',
         '--offset', 0, 0,
       ]},

Docker
```````
Below is an example docker-compose entry for running magpie::

    ocs-magpie:
        image: simonsobs/ocs-magpie:${SOCS_TAG}
        hostname: ocs-docker
        user: ocs:ocs
        network_mode: host
        container_name: ocs-magpie
        volumes:
            - ${OCS_CONFIG_DIR}:/config
            - /data:/data
        command:
            - "--site-hub=ws://${CB_HOST}:8001/ws"
            - "--site-http=http://${CB_HOST}:8001/call"

Lyrebird
------------

Installation
``````````````

In order to build lyrebird, you first need a local build of spt3g-software.
Since we require direct access to the G3 C++ interface, unfortunately we're
not able to use the spt3g / so3g pypi package. You can follow the instructions
on `the SPT3G github page <https://github.com/CMB-S4/spt3g_software>`_ to
build.

Once that is successful, clone the simonsobs fork of 
`lyrebird <https://github.com/simonsobs/lyrebird/tree/generic_datastream>`_,
and follow the build instructions on the lyrebird readme. 

After lyrebird is built successfully, you'll want to add the following lines
to your bashrc:

.. code-block:: bash

   export PATH=/path/to/lyrebird/build/lyrebird-bin:$PATH
   export PATH=/path/to/lyrebird/bin:$PATH

This will add two scripts to your path: 

 - ``lyrebird``, the main lyrebird executable which takes in the path to a cfg
   file specifying data vals, streamer ports, etc. and starts lyrebird from
   that
 - ``run_lyrebird`` which just takes the ports to listen to as
   command line arguments, and will use that to generate a new
   cfg file and start lyrebird from that.

Startup
``````````

To get lyrebird running, you must bring software up in the following order:

1. Make sure smurf-streamers you wish to monitor are running, though data
   doesn't have to actually be streaming
2. Bring up Magpie OCS agents. If streamers are not already running, this
   will currently fail when it begins the ``read`` process. If this happens,
   you can restart the process manually using an OCS client, or just restart
   the agent, which will begin the process on startup. Make sure each magpie
   instance you are running has a different ``stream-id`` and a different
   ``dest`` port.
3. Run lyrebird. The ``lyrebird`` executable takes in a config file that
   specifies data-vals and ports to monitor for G3Streams, but it is much
   easier to use the ``run_lyrebird`` script in the ``lyrebird/bin`` directory.
   This will generate a temporary config file determined by the arguments
   passed in, and then start lyrebird with that config file. Right now
   you need to pass in the ports that it should monitor. For instance,
   if you have two magpie agents running with ``dest`` ports 8675 and 8676,
   you can run::

      run_lyrebird --port 8675 8676

   and this will start lyrebird for the two corresponding slots.


Detector Layouts
-----------------

Grid Layout
````````````
The grid layout is a grid with 4096 elements (maximum number of channels a
single smurf slot can stream)

.. image:: ../_static/images/lyrebird_grid.png
  :width: 400
  :alt: Alternative text

This layout contains 8 rows containing 512 detectors each, with the bottom
row being band 0, and the top row band 7. This is the easiest layout to set up
and is useful for viewing detector response as a function of their resonator
frequency or band / channel id.

Wafer Layout
`````````````

The Wafer layout takes in a det-map CSV file generated from the simonsobs 
`detmap <https://github.com/simonsobs/DetMap.git>`_ package, and uses it
to generate a focal-plane layout.

.. image:: ../_static/images/lyrebird_wafer.png
  :width: 400
  :alt: Alternative text

Additional Streaming Modes
----------------------------

Reading from G3Files
``````````````````````

It is  possible to tell magpie to stream data from existing G3Files instead of
directly from the smurf-stream. To do this, simply set the ``src`` argument to
be the filepath of the file you wish to stream. If you want to stream from
multiple files in series, you can do this by pu::

      {'agent-class': 'MagpieAgent',
       'instance-id': 'magpie-crate1slot2',
       'arguments': [
         '--stream-id', 'crate1-slot2',

         '--src', '/path/to/file1.g3', '/path/to/file2.g3',

         '--dest', 8675,
         '--delay', 5,
         '--target-rate', 20
         '--layout', 'wafer',

         # Detmap CSV file
         '--csv-file', '/home/jlashner/lyrebird_demo/detmap.csv',
         '--offset', 0, 0,
       ]},

Streaming Fake Data
``````````````````````

To stream fake data, add the ``--fake-data`` argument. In this case
you don't need to provide a data-source::

      {'agent-class': 'MagpieAgent',
       'instance-id': 'magpie-crate1slot2',
       'arguments': [
         '--stream-id', 'crate1-slot2',

         '--dest', 8675,
         '--delay', 5,
         '--target-rate', 20
         '--layout', 'wafer',

         # Detmap CSV file
         '--csv-file', '/home/jlashner/lyrebird_demo/detmap.csv',
         '--offset', 0, 0,
         '--fake-data',
       ]},


API
-----

Agent API
``````````

.. autoclass:: agents.magpie.magpie_agent.MagpieAgent
   :members:

Supporting APIs
````````````````````
.. autoclass:: agents.magpie.magpie_agent.FIRFilter
  :members:

.. autoclass:: agents.magpie.magpie_agent.RollingAvg
  :members:

.. autoclass:: agents.magpie.magpie_agent.FocalplaneConfig
  :members:
