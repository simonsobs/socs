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

Docker Container on Windows
---------------------------
This is the recommended configuration, but has yet to be developed and tested
on Windows. Check back soon. In the meantime, you can run on the WSL, as
detailed below.

Dependencies
____________

- Windows 10 Pro/Enterprise
- Docker for Windows

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

An example configuration for your ocs config file::

      {'agent-class': 'BlueforsAgent',
       'instance-id': 'bluefors',
       'arguments': [['--log-directory', '/mnt/c/Users/Dilfridge/Desktop/BlueFors/Logs/']]
      }   

The `--log-directory` argument will need to be updated in your configuration.
