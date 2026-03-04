.. highlight:: rst

.. _bluefors_agent:

==============
Bluefors Agent
==============

The Bluefors Agent is an OCS Agent which tracks the contents of the Bluefors
logs and passes them to the live monitor and to the OCS housekeeping data
aggregator.

.. argparse::
   :module: socs.agents.bluefors.agent
   :func: make_parser
   :prog: agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
```````````````

An example configuration for your ocs config file::

      {'agent-class': 'BlueforsAgent',
       'instance-id': 'bluefors',
       'arguments': [['--log-directory', '/logs']]
      }

.. note::
    The ``--log-directory`` argument will need to be updated in your configuration if
    you are running outside of a Docker container.

Docker Compose
``````````````

Example docker compose configuration::

  ocs-bluefors:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=bluefors
      - LOGLEVEL=info
      - FRAME_LENGTH=600
      - STALE_TIME=2
      - MODE=follow
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /home/simonsobs/bluefors/logs/:/logs:ro

Depending on how you are running your containers it might be easier to hard
code the `OCS_CONFIG_DIR` environment variable.

Environment Variables
^^^^^^^^^^^^^^^^^^^^^
There are several environment variables that can be used to configure the
Bluefors Agent container.

+--------------+----------------------------------------------------------------+
| Variable     | Description                                                    |
+==============+================================================================+
| LOGLEVEL     | Verbosity of the logs.                                         |
+--------------+----------------------------------------------------------------+
| FRAME_LENGTH | .g3 frame length.                                              |
+--------------+----------------------------------------------------------------+
| MODE         | File tracking mode, either "follow" or "poll", defaulting to   |
|              | "poll". In "follow" mode the Tracker will read the next line   |
|              | in the file if able to. In "poll" mode stats about the file    |
|              | are used to determine if it was updated since the last read,   |
|              | and if it has been the file is reopened to get the last line.  |
|              | This is more I/O intensive, but is useful in certain           |
|              | configurations.                                                |
+--------------+----------------------------------------------------------------+
| STALE_TIME   | Time limit (in minutes) for newly opened files to be published |
|              | to feeds. Data older than this time when read will not be      |
|              | published.                                                     |
+--------------+----------------------------------------------------------------+

Description
-----------

The Bluefors Agent tracks the contents of the Bluefors log files, publishing
data as they are written to the log files while the Agent is running. There are
many ways this could be setup to run, depending on your system. In this section
we describe several of those configurations.

The Bluefors software must run on a Windows OS. This may make integrating into
OCS different than on a Linux box (where we run in a Docker container)
depending on your computer configuration.

Running the Bluefors Agent in a Docker container is the recommended
configuration, but you have options for whether that container runs on Windows
or on Linux. If neither of those solutions works, running directly on the
Windows Subsystem for Linux is possible.

Configuring the Bluefors Logs
`````````````````````````````

You should configure your Bluefors software to all log to the same directory.
This will place thermometry logs and system logs in the same date directories
within this top level directory.

Docker Container on Windows
```````````````````````````
Running Docker on Windows can vary a lot depending on what version of Windows
you have, what kind of hardware you are running on, and whether or not you are
running Windows virtually. As such, the setup can change significantly based on
your configuration. We'll try to provide general guidelines for how to setup
the system.

.. note::
    If you run Windows 10 in a virtualized environment you might run into
    difficulty running Docker, depending on what virutalization software you are
    using and what your hardware supports.

Dependencies
^^^^^^^^^^^^

There are various limitations to what you can run on Windows depending on your
configuration. For instance, Docker for Windows doesn't run on Windows 10 Home,
but a legacy tool called Docker Toolbox works.

- Windows 10 Pro/Enterprise
- Docker for Windows

Or:

- Windows 10 Home
- `Docker Toolbox`_ for Windows

Setup
^^^^^

The general outline for setup of `Docker Toolbox`_ (which probably also works on
Windows 10 Pro/Enterprise, but Docker recommends upgrading to more modern
tools, i.e. Docker for Windows, if possible) is:

- Install `Docker Toolbox`_
- Run docker terminal (this performs some Virtualbox setup)
- Run docker login
- Clone the ocs-site-configs repo and create a directory for your machine
- Configure ocs/docker compose files
- Make sure your system clock is set to UTC
- Bring up the container(s)

.. _`Docker Toolbox`: https://docs.docker.com/toolbox/toolbox_install_windows/

Windows Subsystem for Linux
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Windows 10 has a feature called Windows Subsystem for Linux, which allows you
to run Linux CLI tools in Windows. This can be used much like you would if you
were to configure a Linux host to run an OCS Agent. While we recommend running
OCS Agents in Docker containers, this configuration is still possible.

You should refer to the OCS documentation for how to install, but the general
outline is:

- Install git
- Clone the ocs, socs, and ocs-site-configs repositories
- Install ocs and socs
- Configure your ocs-config file and perform the associated setup
- Start the Bluefors agent and command it to acquire data via an OCS client

Docker Container on Linux
`````````````````````````

In some situations it might be better to run the Agent on Linux. This might be
because you run Windows within a virtual environment and write the logs to a
shared filesystem, or if Docker for Windows is difficult to install for
whatever reason. In this later case, if you sync your logs to a Linux system
regularly, i.e. at roughly the rate they are written, you can run the Agent on
that Linux system (or one that also has access to that filesystem.)

In this setup, depending on the syncing mechanism the Agent might need to
reopen the file regularly. It will grab the latest reading from the logs to
publish. Since it's possible that this could be quite old in some scenarios the
timestamp is now checked before publishing. It can be at most ``STALE_TIME``
minutes old. This defaults to two minutes, but can be set with the
``STALE_TIME`` environment variable.

Agent API
---------

.. autoclass:: socs.agents.bluefors.agent.BlueforsAgent
    :members:

Supporting API
--------------

.. autoclass:: socs.agents.bluefors.agent.LogTracker
    :members:

.. autoclass:: socs.agents.bluefors.agent.LogParser
    :members:
