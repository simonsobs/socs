.. highlight:: rst

.. _ls372_simulator:

=======================
Lakeshore 372 Simulator
=======================

The Lakeshore 372 Simulator is meant to mock a Model 372 AC Resistance Bridge
from Lakeshore Cryotronics. This is useful for testing code when you do not
have access to a Lakeshore 372.

The simulator listens on a specified port for a connection as if you were
interacting with a 372 and interprets commands and queries in a similar manner
to the real device.

.. note:: While not all commands are supported, the ones in use by
    the :ref:`Lakeshore 372 Agent<lakeshore372>` are.

.. argparse::
    :filename: ../simulators/lakeshore372/ls372_simulator.py
    :func: make_parser
    :prog: python3 ls372_simulator.py

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
simulator in a docker container.

ocs-config
``````````
The LS372 Simulator is not an OCS Agent, however, you might want to run the
Lakeshore 372 Agent to interact with the LS372 Simulator.  See the
:ref:`Lakeshore 372 Agent<lakeshore372>` page for configuration file details.
The address and port will depend on where you run the simulator, and your
selected port.

Docker
``````
The simulator can be configured to run in a Docker container. An example
docker compose service configuration is shown here::

  ocs-LS372-sim:
    image: ocs-lakeshore372-simulator
    ports:
      - "7777:7777"
