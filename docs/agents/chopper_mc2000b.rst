.. highlight:: rst

.. _chopper_mc2000b_agent:

========================
Thorlabs MC2000B Agent
========================

The Thorlabs MC2000B Agent is an OCS agent which helps monitor input and output
frequencies of the Thorlabs chopper, and sends commands to set the frequency of the chopper,
as well as other features such as the bladetype and reference modes of the device.

Dependencies
------------

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

To configure the Thorlabs MC2000B chopper Agent we need to add a ControllerAgent block to our
ocs configuration file. Here is an example configuration block using all of the
available arguments::

      {'agent-class': 'ControllerAgent',
       'instance-id': 'chopper',
       'arguments': [['--mode', 'acq'],
                     ['--comport', 'COM3']]},

Description
-----------

The ControllerAgent contains methods which control the chopper controller.

Agent API
---------

.. autoclass:: agents.chopper_mc2000b.chopper_mc2000b_agent.ControllerAgent
    :members:
