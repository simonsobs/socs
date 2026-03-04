.. highlight:: rst

.. _rtsp_camera:

====================
RTSP Camera Agent
====================

This OCS Agent which grabs screenshots and records video from IP cameras
supporting the RTSP streaming protocol.

.. argparse::
    :filename: ../socs/agents/rtsp_camera/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

To configure the RTSP Camera Agent we need to add a RTSPCameraAgent block to our
ocs configuration file. Here is an example configuration block using all of the
common arguments. Many options do not normally need to be changed::

      {'agent-class': 'RTSPCameraAgent',
       'instance-id': 'camera-c3',
       'arguments': ['--mode', 'acq',
                     '--directory', '/camera',
                     '--address', 'camera-c3.example.org',
                     '--user', 'ocs',
                     '--password', '<password>',
                     '--motion_start', '19:00:00-04:00',
                     '--motion_stop', '07:00:00-04:00',
                     '--snapshot_seconds', '10',
                     '--record_duration', '120']},

Docker Compose
``````````````

The RTSP camera Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-camera-c3:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    environment:
      - INSTANCE_ID=camera-c3
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
      - LOGLEVEL=info
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /so/cameras/c3:/camera
    user: 9000:9000

The ``LOGLEVEL`` environment variable can be used to set the log level for
debugging. The default level is "info". The volume must mount to whatever
location inside the container that you specified in the config file. The user
must have permissions to write to the mounted local directory.

Description
-----------

The indoor IP cameras at the site support the RTSP protocol. These cameras are
mainly for security monitoring. The directory specified in the configuration is
the top level directory for storing files. Two subdirectories, "snapshots" and
"recordings" are created below this. Snapshots are saved every 10 seconds and a
couple days worth are kept in a circular buffer on disk. A symlink
("latest.jpg") is kept for the latest snapshot acquired, and this can be
displayed in a Grafana text panel using an HTML image tag.

By default, these snapshots are processed for motion detection. If motion is
detected, a 20fps video recording is triggered. During recording, further motion
detection is disabled. After the recording stops, motion detection resumes.
These recordings are also kept in a circular disk buffer in the "recordings"
subdirectory. These full video files are for manual download and viewing after a
security event. All image and video files contain the ISO timestamp when they
were acquired.

Agent API
---------

.. autoclass:: socs.agents.rtsp_camera.agent.RTSPCameraAgent
    :members:
