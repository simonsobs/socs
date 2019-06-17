.. highlight:: rst

.. _lakeshore240:

=============
Lakeshore 240
=============

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
