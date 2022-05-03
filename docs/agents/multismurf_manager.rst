
.. highlight:: rst

.. _multismurfmanager:

====================
MultiSmurf Manager
====================

When scaling up to use multiple smurf-slots, we will need to command tens of
smurf-instances in conjunction. The connection to each smurf-slot will still
but managed by a ``PysmurfControl`` agent, but the ``MultiSmurfManager`` agent
can be used to issue commands to any combination of ``PysmurfControl`` agents
on the network, and read back the session data from each agent.


.. argparse::
    :filename: ../agents/multismurf_manager/multismurf_manager.py
    :func: make_parser
    :prog: python3 multismurf_manager.py

Configuration File Examples
---------------------------

OCS Site Config
```````````````

The MultiSmurfManager does not require any input arguments, so an example
OCS config block is below::

  {'agent-class': 'MultiSmurfManager',
   'instance-id': 'multismurf',
   'arguments': []}

Docker Compose
``````````````
Below is a sample docker-compose service that can be used to run the
multismurf_manager in a container:

The Lakeshore 240 Agent can (and probably should) be configured to run in a
Docker container. An example configuration is::

  ocs-multismurfmanager:
    image: simonsobs/ocs-multismurf-manager:latest
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Usage
--------
This agent will actively monitor heartbeats of all agents on the network to
keep an up-to-date list of what PysmurfControllers are present.

This list can be checked by inspecting the session data of the ``monitor``,
task, which contains information on each PysmurfController on the network
and the session data of each of it's opeations, for instance::

  PUT EXAMPLE HERE

Each operation defined in the PysmurfControl agent is also registered as an
operation for the MultiSmurfManager agent, with the additional argument
``stream_ids``, which lets you specify a list of stream_ids for which the
operation should be run on. By default, if no stream_ids are passed, the
operation will be attempted on all non-expired PysmurfControl instances.
The operation will wait until all smurfs have completed, returning 
``success=True`` only if all agents have completed their operation
successfully.

The ``session.data`` object for the operation will be a dictionary containing
the encoded session-data for each of the commanded PysmurfControl instances,
indexed by stream_id. For example::

  PUT EXAMPLE HERE
Agent API
---------

.. autoclass:: agents.multismurf_manager.multismurf_manager.MultiSmurfManager
    :members:

Supporting APIs
---------------

.. autoclass:: agents.multismurf_manager.multismurf_manager.ManagedSmurfInstance
    :members:
