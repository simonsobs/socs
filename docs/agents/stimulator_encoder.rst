.. highlight:: rst

.. _stm_encoder:

========================
Stimulator Encoder Agent
========================

The optical encoder signals of the stimulator are captured by Kria KR260
boards with the PTP timing reference.
This agent runs inside the KR260 to publish captured data to the crossbar.

.. argparse::
    :filename: ../socs/agents/stimulator_encoder/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent in a docker container.

OCS Site Config
```````````````

To configure the stimulator encoder agent we need to add a StimEncAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'StimEncAgent',
        'instance-id': 'stim-enc',
        'arguments':[]}


Description
-----------

The stimulator is equipped with two optical encoders to monitor the position of the rotating chopper.
The Kria KR260 board is used to capture these encoder signals.
The signal is routed to the programmable logic (PL) in the Zynq Ultrascale+ chip on the Kria.
Changes in the encoder states are captured with the PTP-based timestamp provided by the timestamp unit (TSU) in the Gigabit Ethernet MAC in Zynq.
The packet containing the encoder states and the timestamp is sent to the FIFO inside the PL and is then read from the processor via the AXI interface.
The interface is memory-mapped with the uio (User Space I/O) driver.

The hardware timestamp of the PTP origin is provided in TAI format, which is offset by 37 seconds from UTC at least until December 31, 2025.


Agent API
---------

.. autoclass:: socs.agents.stimulator_encoder.agent.StimEncAgent
    :members:


Supporting APIs
---------------

.. autoclass:: socs.agents.stimulator_encoder.drivers.StimEncError
    :members:

.. autoclass:: socs.agents.stimulator_encoder.drivers.StimEncTime
    :members:

.. autoclass:: socs.agents.stimulator_encoder.drivers.StimEncData
    :members:

.. autoclass:: socs.agents.stimulator_encoder.drivers.StimEncReader
    :members:
