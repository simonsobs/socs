.. highlight:: rst

.. _hwp_picoscope:

======================
HWP Picoscope Agent
======================

The HWP picoscope agent interfaces with Picoscope 3403D MSO to operate the LC sensors which remotely measures the 3 dimentional position and temperature of hwp.
This agent biases the LC sensors and measures the 4 channels of analog input and 8 channels of digital input.

.. argparse::
    :filename: ../socs/agents/hwp_picoscope/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
---------------------------
The Picoscope 3403 MSO requires some drivers to be compiled for your machine.
To install the drivers wget the picotech library and clone the picosdk-python-wrappers repository and build the drivers::

    $ wget https://labs.picotech.com/debian/pool/main/libp/libpicoipp/libpicoipp_1.3.0-4r21_amd64.deb &&\
    $ wget https://labs.picotech.com/debian/pool/main/libp/libps3000a/libps3000a_2.1.0-6r570_amd64.deb &&\
    $ dpkg -i *deb
    $ git clone https://github.com/picotech/picosdk-python-wrappers.git
    $ cd picosdk-python-wrappers
    $ git switch -c 89003868b5bc52511ee57419f0afbfade25f1882
    $ python3 setup.py install

Configuration File Examples
---------------------------
Below are useful configurations examples for the relevant OCS files and for
running the agent in a docker container.

ocs-config
``````````
To configure the HWP picoscope agent we need to add a HWPPicoscopeAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

       {'agent-class': 'HWPPicoscopeAgent',
        'instance-id': 'picoscope',
        'arguments': []}

Docker
``````

.. warning::
    This agent is only confirmed to work with the privileged flag, which disables
    the features that isolate a container from the host system. It is recommended
    that you instead run this Agent directly on the host via the Host Manager
    Agent.

    If you want to run in a container you will need to build the image
    yourself. A Dockerfile is provided in ``socs/docker/hwp_picoscope/``.

The HWP picoscope agent can be run via a Docker container. The following is an
example of what to insert into your institution's docker compose file::

  picoscope:
    image: ocs-hwp-picoscope-agent:latest
    hostname: ocs-docker
    privileged: true
    environment:
      - INSTANCE_ID=picoscope
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /dev:/dev

Agent API
---------

.. autoclass:: socs.agents.hwp_picoscope.agent.PicoAgent
    :members:
