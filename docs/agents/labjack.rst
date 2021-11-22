.. highlight:: rst

.. _labjack:

=============
LabJack Agent
=============

LabJacks are generic devices for interfacing with different sensors, providing
analog and digital inputs and outputs. They are then commanded and queried over
Ethernet.

.. argparse::
    :filename: ../agents/labjack/labjack_agent.py
    :func: make_parser
    :prog: python3 labjack_agent.py


Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the LabJack Agent we need to add a LabJackAgent block to our ocs
configuration file. Here is an example configuration block using all of the
available arguments::

        {'agent-class': 'LabJackAgent',
         'instance-id': 'labjack',
         'arguments':[
           ['--ip-address', '10.10.10.150'],
           ['--active-channels', ['AIN0', 'AIN1', 'AIN2']],
           ['--function-file', 'labjack-functions.yaml'],
           ['--mode', 'acq'],
           ['--sampling-frequency', '700'],
           ]},

You should assign your LabJack a static IP, you'll need to know that here. 
The 'active-channels' argument specifies the channels that will be read out.
It can be a list, 'T7-all', or 'T4-all'. The latter two read out all 
14 or 12 analog channels on the T7 and T4, respectively. 'sampling_frequency'
is in Hz, and has been tested sucessfully from 0.1 to 5000 Hz. To avoid 
high sample rates potentially clogging up live monitoring, the main feed 
doesn't get published to influxdb. Instead influx gets a seperate feed 
downsampled to a maximum of 1Hz. Both the main and downsampled feeds are 
published to g3 files. 

The 'function-file' argument specifies the labjack configuration file, which 
is located in your OCS configuration directory. This allows analog voltage 
inputs on the labjack to be converted to different units. Here is an example 
labjack configuration file::

    AIN0:
        user_defined: 'False'
        type: "MKS390"

    AIN1: 
        user_defined: 'False'
        type: 'warm_therm'

    AIN2:
        user_defined: 'True'
        units: 'Ohms'
        function: '(2.5-v)*10000/v'
        
In this example, channels AIN0 and AIN1 are hooked up to the MKS390 pressure 
`gauge`_ and a `thermistor`_ from the SO-specified warm thermometry setup, 
respectively. Since these are defined functions in the LabJackFunctions class, 
specifying the name of their method is all that is needed. AIN2 shows how to 
define a custom function. In this case, the user specifies the units and the 
function itself, which takes the input voltage 'v' as the only argument.

.. _gauge: https://www.mksinst.com/f/390-micro-ion-atm-modular-vacuum-gauge
.. _thermistor: https://docs.rs-online.com/c868/0900766b8142cdef.pdf

.. note:: 
    The (lower-case) letter 'v' must be used when writing user-defined 
    functions. No other variable will be parsed correctly.

Docker Compose
``````````````

The LabJack Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-labjack:
    image: simonsobs/ocs-labjack-agent:latest
    <<: *log-options
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config
    command:
      - "--instance-id=labjack"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.

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

.. autoclass:: agents.labjack.labjack_agent.LabJackFunctions
    :members:
