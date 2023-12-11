.. highlight:: rst

.. _acti_camera:

====================
ACTi Camera Agent
====================

The ACTi Camera Agent is an OCS Agent which grabs screenshots from ACTi cameras
and saves files to a directory.

.. argparse::
    :filename: ../socs/agents/acti_camera/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the ACTi Camera Agent we need to add a ACTiCameraAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'ACTiCameraAgent',
       'instance-id': 'cameras',
       'arguments': [['--mode', 'acq'],
                     ['--camera-addresses', ['10.10.10.41', '10.10.10.42', '10.10.10.43']],
                     ['--locations', ['location1', 'location2', 'location3']],
                     ['--user', 'admin'],
                     ['--password', 'password']]},

.. note::
    The ``--camera-addresses`` argument should be a list of the IP addresses
    of the cameras on the network.
    The ``--locations`` argument should be a list of names for camera locations.
    This should be in the same order as the list of IP addresses.

Docker Compose
``````````````

The iBootbar Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-cameras:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=cameras
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /mnt/nfs/data/cameras:/screenshots
    user: 9000:9000

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info".
The volume must mount to ``/screenshots``. The user must have permissions to write
to the mounted local directory.

Description
-----------

The ACTi cameras will be used to monitor conditions at the SO site.
The ACTi Camera Agent periodically (1 minute) grabs screenshots from each
camera on the network. The images are saved to a location on disk. A webserver
should then be configured to serve this directory to some URL. Then we can use
HTML to access the webserver and display ``latest.jpg`` for an up-to-date
view of the camera. For example, this can be done directly in Grafana
using the Text panel in HTML mode.

Agent API
---------

.. autoclass:: socs.agents.acti_camera.agent.ACTiCameraAgent
    :members:
