.. highlight:: rst

.. tauhk:

=============
tauHK Agent
=============

The tauHK system is an all in one cryogenic temperature control system.
More information can be found in the accompanying `paper <https://pubs.aip.org/aip/rsi/article/96/9/094902/3363308/HK-A-modular-housekeeping-system-for-cryostats-and>`.

This docs page is currently a stub.
See source code or contact simont@princeton.edu for support.

Building the tauHK Agent
------------------------

This agent relies on protobuf definitions that contain the experiment configurations.
These are shared between the tauHK daemon and the OCS agent.

The agent also expects to communicate with a running instance of the tauHK daemon.
