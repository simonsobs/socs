.. highlight:: rst

.. _stm_encoder:

========================
Stimulator Encoder Agent
========================

The optical encoder signals of the stimulator are captured by Kria KR260
boards with the PTP timing reference.
This agent runs inside the KR260 to publish captured data to the crossbar.

.. argparse::
    :filename: ../socs/agents/stm_encoder/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent in a docker container.

OCS Site Config
```````````````

To configure the stimulator encoder agent we need to add a StmEncAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'StmEncAgent',
        'instance-id': 'stm_enc',
        'arguments':[]}


Description
-----------

The stimulator is equipped with two optical encoders to monitor the position of the rotating chopper.
The Kria KR260 board is used to capture these encoder signals.
The signal is routed to the programmable logic (PL) in the Zynq Ultrascale+ chip on the Kria.
Changes in the encoder states are captured with the PTP-based timestamp provided by the timestamp unit (TSU) in the Gigabit Ethernet MAC in Zynq.
The packet containing the encoder states and the timestamp is sent to the FIFO inside the PL and is then read from the processor via the AXI interface.
The interface is memory-mapped with the uio (User Space I/O) driver.

The timestamp provided by the TSU is in the TAI format.
Since TAI is uniformly incremented even during leap seconds,
translation from TAI to Unix time requires the cumulative offset inserted for leap seconds.
This offset is hard-coded in `drivers.py`.


Agent API
---------

.. autoclass:: socs.agents.stm_encoder.agent.StmEncAgent
    :members:
