.. highlight:: rst

.. _ucsc_radiometer:

=====================
UCSC Radiometer Agent
=====================

The UCSC Radiometer Agent monitors the PWV through the UCSC Radiometer web server.

.. argparse::
    :filename: ../socs/agents/ucsc_radiometer/agent.py
    :func: add_agent_args
    :prog: python3 agent.py

Dependencies
------------

The UCSC Radiometer Agent requires the `UCSC Radiometer Server
<https://github.com/simonsobs/ucscradiometer-server>`_. This server runs where
the radiometer data files are written and makes readings available to the Agent
over HTTP.

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container

OCS Site Config
```````````````

To configure the UCSC Radiometer Agent we need to a UCSCRadiometerAgent
block to our ocs configuration file. Here is an example configuration block
using all of the available arguments::

        {'agent-class': 'UCSCRadiometerAgent',
         'instance-id': 'pwvs',
         'arguments':[['--url', 'http://127.0.0.1:5000']]},

.. note::
   The ``--url`` argument should be the address of the Flask server on the
   Web which is publishing pwv data from a server connected to the
   radiometer on-site.

Docker Compose
``````````````

The UCSC Radiometer Agent should be configured to run in a Docker container. An
example docker-compose service configuration is shown here::

  ocs-ucsc-radiometer:
       image: simonsobs/socs:latest
       hostname: ocs-docker
       network_mode: host
       volumes:
           - ${OCS_CONFIG_DIR}:/config
       environment:
           - INSTANCE_ID=pwvs

Description
-----------

The UCSC radiometer measures precipitable water vapor (pwv) of the atmosphere,
and outputs the values to disk on a computer at the site where OCS
is not setup. A web server makes the PWV values available over HTTP. The Agent requests the PWV data and then publishes it to OCS.

Agent API
---------

.. autoclass:: socs.agents.ucsc_radiometer.agent.UCSCRadiometerAgent
    :members:
