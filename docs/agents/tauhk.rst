.. highlight:: rst

.. _tauhk:

===========
tauHK Agent
===========

The tauHK system is an all in one cryogenic temperature control system.
More information can be found in the accompanying `paper <https://pubs.aip.org/aip/rsi/article/96/9/094902/3363308/HK-A-modular-housekeeping-system-for-cryostats-and>`_.

.. argparse::
    :filename: ../socs/agents/tauhk/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
------------

The tauHK hardware comumunicates over ethernet with a static IP setup.
The hardware for the LAT has been configured to a static IP ``10.1.0.74`` and expects the control computer to be found at ``10.1.0.77``.

``amun`` has been outfitted with a usb to ethernet device, this device can be configured with::

    $ sudo ip addr add 10.1.0.77/24 dev enx14ebb6850591 # set the IP 
    $ sudo ip link set enx14ebb6850591 up #bring up the dev if it is down (does not show up in ifconfig without -a flag)

The direct interaction with the hardware is handled by a percompiled binnary, please contact a member of the taurus cmb collaboration to obtain a copy.
This binary must be named ``tauhk-agent`` and placed in the same directoy as the ``agent.py``.

Finally, channel mappings must be provided in the form of a `protobuf <https://protobuf.dev/>`_ file descriptor. 
This file descriptor is generated from a experiment configuration yaml with the following syntax::

  - rtd: # RTD card type
      position: 2 # Physical card position in the crate (zero indexed)
      channels:
        - name: rtd_0 # Channel name mapping
          channel: 0 # Card channel number (zero indexed)
          lut: luts/table.lut # path to look up table for converting from native units to temperature
        - name: rtd_1 # Name is mandatory
          channel: 1 # Channel number is mandatory
          # lut is optional
  - diode: # Diode card type
      position: 4
      channels:
        - name: diode_0
          channel: 0
          lut: /abs_path/table.lut

The config file is then turned into a ``.proto`` file with ``python3 generate_proto`` which is turned into a file descriptor with::

  $ protoc --file-descriptor-out=descriptor.bin --include-imports system.proto

The tauHK binary expects this file descriptor to be named ``descriptor.bin`` in the same directoy as ``agent.py``.

For tauHK to output data in temperature units, lookup tables must be provided.
These lookup tables need to formated as follows::

  # Comments must have a leading pound sign
  # Data must be in sorted increasing order
  # Map from native units (ohms for RTD and volts for Diode) to temperature
  0.234515  300
  0.245463  275
  # and so on...

Configuration File Examples
---------------------------

Todo. if this is dockerized this will look different I suspect

Example Clients
---------------

Device Configuration
````````````````````

The tauHK agent will not stream data (or really do anything) on it's own.
First, the binary must be launched with the ``start_crate`` process, the logs from the binary are re-logged into the agent logs for introspection.
To begin logging data the ``recieve_data`` process must be run, this starts the data stream to influx and to ``.g3`` files.

Commands can be sent via the ``generic_send`` task, allowing users to command individual channels or with ``load_excitation`` for multiple channels at the same time.

Agent API
---------

.. autoclass:: socs.agents.tauhk.agent.TauHKAgent
    :members:
