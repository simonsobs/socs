.. highlight:: rst

.. _lakeshore240:

=============
Lakeshore 240
=============

The Lakeshore 240 is a 4-lead meausrement device used for readout of ROXes and
Diodes at 1K and above.

Driver Setup
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

To install the drivers clone the ls240_drivers repository and run ``make`` to
build the drivers::

    $ git clone https://github.com/simonsobs/ls240-drivers.git
    $ make

Update the udev rules file, ``50-ls240.rules``, adding an entry for your
devices' serial numbers, then run::

    $ make install_udev

If your devices were plugged in already you will need to unplug and replug them
for the udev rules to properly recognize the devices and set the path and
permissions appropriately. Once you complete this step they will be recongized
on reboots, and the udev rules will not need to be reinstalled unless you add a
new device.

OCS Configuration
-----------------

To configure your Lakeshore 240 for use with OCS you need to add a
Lakeshore240Agent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'Lakeshore240Agent',
   'instance-id': 'LSA22Z2',
   'arguments': [['--serial-number', 'LSA22Z2'],
                 ['--num-channels', 8]]},

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Docker Configuration
--------------------

The Lakeshore 240 Agent can (and probably should) be configured to run in a
Docker container. An example configuration is::

  ocs-LSA24MA:
    image: grumpy.physics.yale.edu/ocs-lakeshore240-agent:latest
    depends_on:
      - "sisock-crossbar"
    devices:
      - "/dev/LSA24MA:/dev/LSA24MA"
    hostname: nuc-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
    command:
      - "--instance-id=LSA24MA"
      - "--site-hub=ws://sisock-crossbar:8001/ws"
      - "--site-http=http://sisock-crossbar:8001/call"

The serial number will need to be updated in your configuration. The hostname
should also match your configured host in your OCS configuration file. The
site-hub and site-http need to point to your crossbar server, as described in
the OCS documentation.
