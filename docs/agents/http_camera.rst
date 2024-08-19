.. highlight:: rst

.. _http_camera:

====================
HTTP Camera Agent
====================

The HTTP Camera Agent is an OCS Agent which grabs screenshots from cameras
using HTTP requests and saves files to a directory.

.. argparse::
    :filename: ../socs/agents/http_camera/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the HTTP Camera Agent we need to add an HTTPCameraAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

      {'agent-class': 'HTTPCameraAgent',
       'instance-id': 'cameras',
       'arguments': [['--mode', 'acq'],
                     ['--config-file', 'cameras.yaml']]},

.. note::
    The ``--config-file`` argument should be the config file path relative
    to ``OCS_CONFIG_DIR`` and contain an entry for each camera with
    relevant information. An example is given below which is also found
    at `config`_.

.. _config: https://github.com/simonsobs/socs/blob/main/socs/agents/http_camera/sample_config.yaml

Docker Compose
``````````````

The HTTP Camera Agent should be configured to run in a Docker container. An
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

Camera Config
`````````````

.. literalinclude:: ../../socs/agents/http_camera/sample_config.yaml
   :language: yaml

Description
-----------

The HTTP cameras will be used to monitor conditions at the SO site.
The HTTP Camera Agent periodically (1 minute) grabs screenshots from each HTTP
camera on the network. The images are saved to a location on disk. A webserver
should then be configured to serve this directory to some URL. Then we can use
HTML to access the webserver and display ``latest.jpg`` for an up-to-date
view of the camera. For example, this can be done directly in Grafana
using the Text panel in HTML mode.

Agent API
---------

.. autoclass:: socs.agents.http_camera.agent.HTTPCameraAgent
    :members:
