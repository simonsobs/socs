.. highlight:: rst
.. _honeywell_HMR2300:
==================
Honeywell HMR2300
==================
The Honeywell HMR2300 is a three-axis smart digital magnetometer to
detect the strength and direction of an incident magnetic field. The three of
Honeywell’s magneto-resistive sensors are oriented in orthogonal
directions to measure the X, Y and Z vector components of a magnetic
field. This agent is to read the magnetic field strength.

.. argparse::
    :filename: ../agents/honeywell_HMR2300/honeywell_HMR2300.py
    :func: make_parser
    :prog: python3 honeywell_HMR2300.py
    
    
Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
To configure the Honeywell HMR2300 we need to add a HoneywellHMR2300
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

 {'agent-class': 'HoneywellHMR2300',
       'instance-id': 'HMR2300',
       'arguments': [['--acq', True],
                    ['--ip', '10.10.10.132'],
                    ['--port', '4001'],
                    ['--baudrate', '9600'],
                    ['--sample-rate', '10'],
                    ['--acq_chunk', '2']
                    ]},

       ]
    }


The baud rate is either 9600 or 19200. 9600 is the default after power 
restart, but 19200 is required to run at sample rates 40Hz or 50Hz. When 
changing the baud rate, make sure to change the moxa box baud rate setting
too.

Docker
``````
The Honeywell HMR2300 should be configured to run in a Docker container.
An example docker-compose service configuration is shown here::

 ocs-HMR2300:
    image: simonsobs/ocs-hmr2300-agent
    <<: *log-options
    hostname: duke-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=HMR2300"
      - "--site-hub=ws://10.10.10.50:8001/ws"
      - "--site-http=http://10.10.10.50:8001/call"

Since the agent within the container needs to communicate with hardware on the
host network you must use ``network_mode: "host"`` in your compose file.
                                                      

Example Client
--------------
Below is an example client to start data acquisition. 'Send_serial_command'
sends any serial command listed in the manual and returns the reply::]

# stop the acq

from ocs import matched_client
mag = matched_client.MatchedClient('HMR2300', args=[])
mag.acq.stop()
status, message, session = mag.acq.wait()
print(status, message, session)

# start acq

sample_rate = 50 #Hz
acq_chunk = 100 #Number of seconds to continuously acquire data for
if sample_rate > 30:
    print("Make sure baudrate is 19200")
from ocs import matched_client
mag = matched_client.MatchedClient('HMR2300', args=[])
mag.acq.start(sample_rate=sample_rate, acq_chunk = acq_chunk)

# Set baudrate

baudrate = 19200 #must be 19200 or 9600
from ocs import matched_client
mag = matched_client.MatchedClient('HMR2300', args=[])
#Stop acq if it currently running
mag.acq.stop()
status, message, session = mag.acq.wait()
mag.set_baudrate.start(baudrate=baudrate)
status, message, session = mag.set_baudrate.wait()
print("WARNING: Change baud rate settings on moxa box")
print(status, message, session)

#Send a serial command

from ocs import matched_client
mag = matched_client.MatchedClient('HMR2300', args=[])
mag.acq.stop()
status, message, session = mag.acq.wait()
mag.send_serial_command.start(command= "*00ZN", write_enabled = True)
status, message, session = mag.send_serial_command.wait()
print(status, message, session)

Agent API
---------

.. autoclass:: agents.honeywell_HMR2300.honeywell_HMR2300.HoneywellHMR2300Agent
    :members: acq, send_serial_command, set_baudrate