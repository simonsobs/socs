.. highlight:: rst

.. _thorlabs_mc2000b_agent:

========================
Thorlabs MC2000B Agent
========================

The Thorlabs MC2000B Agent is an OCS agent which helps monitor input and output
frequencies of the Thorlabs chopper, and sends commands to set the frequency of the chopper,
as well as other features such as the bladetype and reference modes of the device.

Dependencies
------------

This agent requires running on a Windows machine outside a Docker container. This requires
manually setting the environment variable for $OCS_CONFIG_DIR to the ocs-site-configs path on
your computer. Because we are outside a Docker container, the Thorlabs MC2000B agent will also
need to run in the $OCS_CONFIG_DIR path. Instructions for setting an environment variable on
a Windows computer:

- `Set Env Variable in Windows <https://docs.oracle.com/en/database/oracle/machine-learning/oml4r/1.5.1/oread/creating-and-modifying-environment-variables-on-windows.html#GUID-DD6F9982-60D5-48F6-8270-A27EC53807D0>`_

Python Packages
```````````````

The MC2000B optical chopper is a Thorlabs device. To use the Agent, a software package must be installed
from Thorlabs' website. The software package includes the Python software development kit for third-party
development. That software is imported as MC20000B_COMMAND_LIB in the OCS Agent.

- `MC2000B python command library <https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=MC2000B>`_



Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file.

OCS Site Config
````````````````

To configure the Thorlabs MC2000B chopper Agent we need to add a ThorlabsMC2000BAgent block to our
ocs configuration file. Here is an example configuration block using all of the
available arguments::

      {'agent-class': 'ThorlabsMC2000BAgent',
       'instance-id': 'chopper',
       'arguments': [['--mode', 'acq'],
                     ['--com-port', 'COM3']]},

Description
-----------

The Thorlabs MC2000B Agent takes in 15 bladetypes, the names of which can be found at the link below
under Single and Dual Frequency Optical Chopper Blades and Harmonic Frequency Optical Chopper Blades
as the item number:

- `Bladetyes <https://www.thorlabs.com/newgrouppage9.cfm?objectgroup_id=287>`_

Agent API
---------

.. autoclass:: socs.agents.thorlabs_mc2000b.agent.ThorlabsMC2000BAgent
    :members:
