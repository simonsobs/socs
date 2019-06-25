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
depending on your computer configuration. We'll discuss possible (and
recommended) configurations here.

Configuration Examples
----------------------
Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

ocs-config
``````````
An example configuration for your ocs config file::

      {'agent-class': 'BlueforsAgent',
       'instance-id': 'bluefors',
       'arguments': [['--log-directory', '/mnt/c/Users/Dilfridge/Desktop/BlueFors/Logs/']]
      }

The `--log-directory` argument will need to be updated in your configuration.

Docker
``````
Example docker-compose configuration::

  ocs-bluefors:
    image: grumpy.physics.yale.edu/ocs-bluefors-agent:latest
    hostname: ocs-docker
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro
      - /home/simonsobs/bluefors/logs/:/logs:ro

The logs directory should be mounted inside the container to `/logs` and
configured for that directory in your ocs-config file.



Docker Container on Windows
---------------------------
This is the recommended configuration, but has yet to be developed and tested
on Windows. Check back soon. In the meantime, you can run on the WSL, as
detailed below.

Dependencies
````````````
There are various limitations to what you can run on Windows depending on your
configuration. For instance, Docker for Windows doesn't run on Windows 10 Home,
but a legacy tool called Docker Toolbox works.

- Windows 10 Pro/Enterprise and Docker for Windows

Or:

- Windows 10 Home and Docker Toolbox for Windows

Setup
`````
The general outline for setup of Docker Toolbox (which should also work on
Windows 10 Pro/Enterprise) is:

- Install Docker Toolbox
- Run docker terminal (this performs some Virtualbox setup)
- Run docker login
- Clone the ocs-site-configs repo and create a directory for your machine
- Configure ocs/docker-compose files
- Make sure your system clock is set to UTC
- Bring up the container(s)

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
