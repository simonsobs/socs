.. highlight:: rst

.. _ls240_simulator:

=======================
Lakeshore 240 Simulator
=======================

The Lakeshore 240 Simulator is meant to mock a 240 Series Input Module from
Lakeshore Cryotronics. This is useful for testing code when you do not have
access to a Lakeshore 240.

The simulator opens a socket port and interprets commands and queries in a
similar manner to the real device. Not all Lakeshore 240 commands actually do
something currently, but you can set and read channel variables (even though
they don't change anything) and read data from channels, which will currently
return white noise centered around zero.

.. argparse::
    :filename: ../simulators/lakeshore240/ls240_simulator.py
    :func: make_parser
    :prog: python3 ls240_simulator

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
simulator in a docker container.

ocs-config
``````````
The LS240 Simulator is not an OCS Agent, however, to connect to it you will
need a Lakeshore240Agent configured to communicate with the simulator. We can
do this by passing a full address to the `--port` argument on a
Lakeshore240Agent. This address must match the container name for the simulator::

      {'agent-class': 'Lakeshore240Agent',
       'instance-id': 'LSSIM',
       'arguments': [['--serial-number', 'LSSIM'],
                     ['--port', 'tcp://ls240-sim:1094'],
                     ['--mode', 'acq']]},

Docker
``````
The simulator should be configured to run in a Docker container. An example
docker compose service configuration is shown here::

  ls240-sim:
    image: simonsobs/ocs-lakeshore240-simulator:latest
    hostname: ocs-docker

It is helpful to have other live monitor components such as Grafana and an
InfluxDB container for quickly visualizing whether the 240 Agent is getting
data from the simulator.

Running Outside of Docker
-------------------------
Running ``python3 ls240_simulator.py`` will start the simulator and it will
wait for a connection. To connect to it, you can use the same Lakeshore240.py
module that is used to connect to the real device, but by providing
``port=`tcp::/<address>:<port>'`` instead of the device port.
For instance, if you run ``python3 ls240_simulator.py -p 1000``, you can connect
by providing the Lakeshore240 module with ``port="tcp://localhost:1000"``.
You can specify the port for a LS240 agent in the site-file or through the command line.
