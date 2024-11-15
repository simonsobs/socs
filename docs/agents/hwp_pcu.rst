.. highlight:: rst

.. _hwp_pcu:

=============
HWP PCU Agent
=============

The HWP Phase Compensation Unit (PCU) Agent interfaces with a 8 channel USB relay module
(Numato Lab, product Number SKU:RL80001) to apply the discrete phase compensation in
120-degree increments for the HWP motor drive circuit. When used in conjunction with
a HWP pid controller, phase compensation in 60-degree increments can be achieved.
The HWP PCU can also force the HWP to stop by making the phases of all three-phase
motors the same.

.. argparse::
    :filename: ../socs/agents/hwp_pcu/agent.py
    :func: make_parser
    :prog: python3 agent.py

Dependencies
------------

The PCU device shows up on the system as ``/dev/ttyACMx`` where ``x`` is not
guaranteed to be consistent. To solve this issue we should create a udev rule
for the PCU device. Establish the udev rule by creating a file in
``/etc/udev/rules.d/`` with the following contents::

  SUBSYSTEM=="tty", ATTRS{idVendor}=="2a19", ATTRS{idProduct}=="0c02", MODE="0666", SYMLINK="PCU"

.. note::
    If multiple PCU devices are connected to the same computer you will want to
    include the serial number in the rules, which you can add with
    ``ATTRS{serial}=="<serial number of PCU>"``.

If the PCU was connected to the computer already you will need to unplug and
replug it for the udev rule to properly recognize the device, create the
symlink, and set the permissions appropriately. Once you complete this step the
device will be recongized on reboot, and the udev rules will not need to be
reinstalled unless you add a new device. The PCU should now be available at
``/dev/PCU``.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure your HWP PCU Agent for use with OCS you need to add a
HWPPCUAgent block to your ocs configuration file. Here is an example
configuration block that will automatically start data acquisition::

  {'agent-class': 'HWPPCUAgent',
   'instance-id': 'hwp-pcu',
   'arguments': ['--port', '/dev/HWPPCU']},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Compose
``````````````

The HWP PCU Agent can (and probably should) be configured to run in a
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

To apply 120-degree phase compensation::

    from ocs.matched_client import MatchedClient

    hwp_pcu_client = MatchedClient("HWPPCU")

    hwp_pcu_client.set_command(command='on_1')

To apply 60 (= -120 + 180) degree phase compensation::

    from ocs.matched_client import MatchedClient

    hwp_pcu_client = MatchedClient("HWPPCU")
    hwp_pid_client = MatchedClient("HWPPID")

    hwp_pcu_client.set_command(command='on_2')
    hwp_pid_client.set_direction(direction=1)

Agent API
---------

.. autoclass:: socs.agents.hwp_pcu.agent.HWPPCUAgent
    :members:
