.. highlight:: rst

.. _generator:

====================
Generator Agent
====================

The Generator Agent is an OCS Agent which monitors on-site generators via Modbus.

.. argparse::
    :filename: ../socs/agents/generator/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the Generator Agent we need to add a GeneratorAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'GeneratorAgent',
       'instance-id': 'generator',
       'arguments': [['--host', '192.168.2.88'],
                     ['--port', 5021],
                     ['--mode', 'acq'],
                     ['--configdir', 'G1_config'],
                     ['--sample-interval', 10]
                     ]}

.. note::
    The ``--host`` argument should be the IP address of the generator on the network.

    The '--configdir' argument specifies a directory name for configuration files
    relative to the $OCS_CONFIG_DIR environment variable.

Docker Compose
``````````````

The Generator Agent should be configured to run in a Docker container. An
example docker compose service configuration is shown here::

  ocs-generator:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    environment:
      - INSTANCE_ID=generator
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info


The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".

Description
```````````

On-site generators will be used to provide power to the SO site.
Each generator has the same controller/interface, the Deep Sea Electronics (DSE)
8610 mark II. The Generator Agent allows the monitoring of each generator controller
via Modbus. It queries registers and publishes data in an acquisition process. The
agent has been tested with on-site generators.

The Generator Agent requires a configuration directory which contains information on all
registers that it queries from the generator controller.

Agent Fields
````````````
The fields consist of the register name and the last value, which are necessarily
formatted depending on the register.

Configuration
`````````````
A direcotry of .yaml configuration files is one of the arguments to the agent.
A single .yaml file specifies meta-data about a continuous block of registers to
read. The agent will interpret all .yaml files in the specified directory as
specifications of register blocks.

A single .yaml file must contain keys that specify which registers to read and
how to interpret the data contained in those registers. The key 'read_start' or
'page' must be specified, where 'read_start' is the register offset to begin reading
at, and 'page' is a shorthand for read_start = 256 * page because the DSE GenComm
documentation lists all registers as an offset from their page number. If both keys
are specified, 'read_start' is given preference.

The configuration file must also specify 'read_len', which is how many registers to read
beyond the 'read_start' value.

The 'registers' key contains a dictionary with information about how to interpret the data
contained in the registers that are read. There is no requirement to read all registers
returned in the block, and the same registers can be interpreted by multiple entries in
the 'registers' key.

An example 'registers' entry is contained below::

  Engine_fuel_level:
    max_val: 130.0
    min_val: 0.0
    offset: 3
    read_as: 16U
    scale: 1.0
    units: '%'

They key for each register entry is a description of what information the register contains.
The sub-keys 'offset', 'read_as', 'scale', and 'units' are required entries, but 'max_val' and
'min_val' are optional.

read_as must be one of 16U, 16S, 32U, 32S, or bin. These specify how the data in the register
contained at the specified offset should be interpereted: 16 bit unsigned (16U), 16 bit signed (16S),
32 bit unsigned (32U), 32 bit signed (32S) or binary (bin). When the 32 bit data types are used, it is
implied that the register one byond the specified offset is also being read because each register is
only 16 bits long. In this case binary corresponds to reading a value from an individual bit or range of
bits within a single 16 bit register. A single bit can be read by specifying i.e. 'bin 2' which would
correspond to reading the second most significant bit out of the register, and a range can be specified
by i.e. 'bin 5-8'. The values specified by 'bin' are one-indexed, following the GenComm documentation
specifications. An example of reading different binary values out of the same register follows::

  Alarm_emergency_stop:
    offset: 1
    read_as: bin 13-16
    units: None
  Alarm_low_oil_pressure:
    offset: 1
    read_as: bin 9-12
    units: None

Finally, the file must specify the 'block_name' key which is a description of what the continuous
block of registers contains.

Agent API
---------

.. autoclass:: socs.agents.generator.agent.GeneratorAgent
    :members:
