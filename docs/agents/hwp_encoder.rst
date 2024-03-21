.. highlight:: rst

.. _chwp_encoder:

=====================
HWP Encoder BBB Agent
=====================

The optical encoder signals of the CHWP are captured by Beaglebone Black (BBB)
boards with the IRIG-B timing reference.
This agent receives and decodes UDP packets from BBB and publishes the data
feeds.

.. argparse::
    :filename: ../socs/agents/hwp_encoder/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent in a docker container.

OCS Site Config
```````````````

To configure the CHWP encoder BBB agent we need to add a HWPBBBAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA0',
        'arguments': [
          ['--port', '8080'],
          ]}
       {'agent-class': 'HWPBBBAgent',
        'instance-id': 'HBA1',
        'arguments': [
          ['--port', '8081'],
          ]}

This is an example to run two agents because we usually have a couple of
BBBs for A and B phase of the optical encoder for some redundancy.
Multiple BBBs on the same network are distinguished by port numbers.
You should assign a port for each BBB, which should be consistent with
the setting on the BBB side.

Docker Compose
``````````````

The CHWP BBB agent can be run via a Docker container. The following is an
example of what to insert into your institution's docker-compose file.
This again is an example to run multiple agents::

  ocs-hwpbbb-agent-HBA0:
    image: simonsobs/socs:latest
    ports:
      - "8080:8080/udp"
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=HBA0
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

  ocs-hwpbbb-agent-HBA1:
    image: simonsobs/socs:latest
    ports:
      - "8081:8081/udp"
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=HBA1
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

Description
-----------

session.data
````````````
The most recent data collected is stored in session.data in the following structure.
The approx_hwp_freq is initialized by -1 and will be updated by non-negative rotation frequency
if encoder agent is receiving encoder signal.
If chwp is completely stopped, approx_hwp_freq will not be updated.::

    >>> response.session['data']
    {'approx_hwp_freq':      2.0,
     'encoder_last_updated': 1659486962.3731978,
     'irig_time':            1659486983,
     'irig_last_updated':    1659486983.8985631}

Beaglebone Packet structure
`````````````````````````````
.. list-table:: Encoder Packet Structure v1
   :widths: 20 20 60
   :header-rows: 1

   * - Field
     - Type
     - Description

   * - header
     - unsigned long
     - Packet header to signal encoder info. This will be ``0x2eaf`` for packet
       versions >= 1

   * - version
     - unsigned long
     - The version of the packet

   * - num_samples
     - unsigned long
     - The number of samples in the packet. Each sample has three 32 bit fields, the clock counter, the clock overflow, and the edge counter.

   * - quad
     - unsigned long
     - Quad of the first sample in the packet. This will either be 1 or 0.

   * - packet_counter
     - unsigned long
     - Counter that is incremented each time a packet is sent from the beaglebone

   * - buffer_reset_counter
     - unsigned long
     - Counter that is incremented each time the encoder buffer on the
       beaglebone is reset

   * - clock counts
     - array of ``nsamp`` unsigned longs
     - lower 32 bits of the PRU clock counter

   * - clock overflow
     - array of ``nsamp`` unsigned longs
     - upper 32 bits of the PRU clock counter

   * - Edge indexes
     - array of ``nsamp`` unsigned longs
     - sample counter, incremented for each edge detected in th PRU
  

Agent API
---------

.. autoclass:: socs.agents.hwp_encoder.agent.HWPBBBAgent
    :members:
