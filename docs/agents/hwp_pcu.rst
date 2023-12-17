.. highlight:: rst

.. _lakeshore240:

=============
HWP phase compenation
=============

The Lakeshore 240 is a 4-lead meausrement device used for readout of ROXes and
Diodes at 1K and above.

.. argparse::
    :filename: ../socs/agents/lakeshore240/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
------------

The Lakeshore 240 requires USB drivers to be compiled for your machine. A
private repository, `ls240_drivers`, with the required drivers is available on
the Simons Observatory Github. This repository provides some other helpful
tools, including a set of udev rules for setting the device address
automatically when the 240s are connected to the computer.

.. note::
    The 240 drivers are compiled for the specific kernel you are running at
    installation. If your kernel is updated the drivers will no longer work.
    The DKMS module provided by the `ls24_drivers` repository attempts to solve
    this problem, but does not currently appear to work. Please report any
    difficulty with the drivers to Brian.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure your Lakeshore 240 for use with OCS you need to add a
Lakeshore240Agent block to your ocs configuration file. Here is an example
configuration block that will automatically start data acquisition::

  {'agent-class': 'HWPPCUAgent',
   'instance-id': 'hwp-pcu',
   'arguments': [['--port', '/dev/HWPPCU'],
                 ['--mode', 'acq']]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Compose
``````````````

The Lakeshore 240 Agent can (and probably should) be configured to run in a
Docker container. An example configuration is::

  ocs-hwp-pcu:
    image: simonsobs/socs:latest
    devices:
      - "/dev/HWPPCU:/dev/HWPPCU"
    hostname: nuc-docker
    environment:
      - INSTANCE_ID=hwp-pcu
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro

The serial number will need to be updated in your configuration. The hostname
should also match your configured host in your OCS configuration file. The
site-hub and site-http need to point to your crossbar server, as described in
the OCS documentation.


Example Clients
---------------

Device Configuration
````````````````````

Out of the box, the Lakeshore 240 channels are not enabled or configured
to correctly measure thermometers. To enable, you can use the
:func:`agents.lakeshore240.LS240_agent.LS240_Agent.set_values` Task of the
LS240 Agent to configure a particular channel. Below is an example of a
client that sets Channel 1 of a 240 to read a diode::

    from ocs.matched_client import MatchedClient

    hwp_pcu_client = MatchedClient("HWPPCU")

    hwp_pcu_client.set_command(command='on_1')

Agent API
---------

.. autoclass:: socs.agents.lakeshore240.agent.LS240_Agent
    :members:

Supporting APIs
---------------

.. autoclass:: socs.Lakeshore.Lakeshore240.Module
    :members:
