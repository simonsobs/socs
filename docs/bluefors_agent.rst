.. highlight:: rst

.. _bluefors_agent:

==============
Bluefors Agent
==============

The Bluefors Agent is an OCS Agent which tracks the contents of the Bluefors
logs and passes them to the live monitor and to the OCS housekeeping data
aggregator.

The Bluefors software must run on a Windows OS. This may make integrating into
OCS different than on a linux box (where we run in a Docker container)
depending on your computer configuration.

Running the Bluefors Agent in a Docker container is the recommended
configuration, but you have options for whether that container runs on Windows
or on Linux. If neither of those solutions works, running directly on the
Windows Subsystem for Linux is possible.

Configuring the Bluefors Logs
-----------------------------
You should configure your Bluefors software to all log to the same directory.
This will place thermometry logs and system logs in the same date directories
within this top level directory.

Docker Container on Windows
---------------------------
Running Docker on Windows can vary a lot depending on what version of Windows
you have, what kind of hardware you are running on, and whether or not you are
running Windows virtually. As such, the setup can change significantly based on
your configuration. We'll try to provide general guidelines for how to setup
the system.

Dependencies
````````````
There are various limitations to what you can run on Windows depending on your
configuration. For instance, Docker for Windows doesn't run on Windows 10 Home,
but a legacy tool called Docker Toolbox works.

- Windows 10 Pro/Enterprise
- Docker for Windows

Or:

- Windows 10 Home
- `Docker Toolbox`_ for Windows

Setup
`````
The general outline for setup of `Docker Toolbox`_ (which probably also works on
Windows 10 Pro/Enterprise, but Docker recommends upgrading to more modern
tools, i.e. Docker for Windows, if possible) is:

- Install `Docker Toolbox`_
- Run docker terminal (this performs some Virtualbox setup)
- Run docker login
- Clone the ocs-site-configs repo and create a directory for your machine
- Configure ocs/docker-compose files
- Make sure your system clock is set to UTC
- Bring up the container(s)

.. _`Docker Toolbox`: https://docs.docker.com/toolbox/toolbox_install_windows/

Docker Container on Linux
-------------------------
If you are running your Windows 10 installation in a virtualized environment
then you may have difficulty running Docker, depending on what virtualization
software you are using and what type of CPU you have. In this case we suggest
you log to directory that is shared with the host and run the bluefors Agent
docker container on the Linux host. The configuration should be similar to that
outlined above, but with different paths.

Windows Subsystem for Linux
---------------------------
Windows 10 has a feature called Windows Subsystem for Linux, which allows you
to run Linux CLI tools in Windows. This can be used much like you would if you
were to configure a linux host to run an OCS Agent. While we recommend running
OCS Agents in Docker containers, this configuration is still possible.

You should refer to the OCS documentation for how to install, but the general
outline is:

- Install git
- Clone the ocs, socs, and ocs-site-configs repositories
- Install ocs and socs
- Configure your ocs-config file and perform the associated setup
- Start the Bluefors agent and command it to acquire data via an OCS client
- Create a sisock-data-feed-server container for live monitoring

Configuration File Examples
---------------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
An example configuration for your ocs config file::

      {'agent-class': 'BlueforsAgent',
       'instance-id': 'bluefors',
       'arguments': [['--log-directory', '/logs']]
      }

The `--log-directory` argument will need to be updated in your configuration if
you are running outside of a Docker container.

Docker
``````
Example docker-compose configuration::

  ocs-bluefors:
    image: grumpy.physics.yale.edu/ocs-bluefors-agent:latest
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /home/simonsobs/bluefors/logs/:/logs:ro
    environment:
      LOGLEVEL: "info"
      FRAME_LENGTH: 600

Depending on how you are running your containers it might be easier to hard
code the `OCS_CONFIG_DIR` environment variable.
