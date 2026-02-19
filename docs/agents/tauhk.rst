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

This agent relies on `protobuf <https://protobuf.dev/>` definitions that contain the experiment specific channel mappings.
These definitions are shared between the tauHK daemon and the OCS agent.

To build these specific definitions, obtain a copy of the tauHK protobuf definitions and generator scripts.
The experiment config yaml file is parsed by the python `build_protos.py` generator to produce a `system.proto`.

The `system.proto`, along with it's dependants, is used to generate two build artifacts, one consumed by the deamon and one by the OCS agent.

These are generated with:
`protoc --descriptor_set_out=tauhk_descriptor_set.bin --include_imports -I protos -I protos/include protos/system.proto`
`protoc --python_out=. -I protos -I protos/include protos/system.proto` (note that line 14 must be modified due to a quirk to be `from .include import ...`)

Once these are copied to their correct locations then the agent must be restarted and the configuration will have taken effect.
