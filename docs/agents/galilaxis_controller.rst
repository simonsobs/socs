.. highlight:: rst

.. _galilaxis_controller:

=====================
Galil Axis Controller
=====================

The Galil DMC Axis Controller Agent provides motion control and telemetry readout for
the Galil DMC motor controller. When used in the Simons Observatory SAT Coupling
Optics system, the agent controls four axes—two linear and two angular—that move
the hardware as needed to perform detector passband measurements.


.. argparse::
    :filename: ../socs/agents/galildmc_axis_controller/agent.py
    :func: make_parser
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure your Lakeshore 372 for use with OCS you need to add a
Lakeshore372Agent block to your ocs configuration file. Here is an example
configuration block::

  {'agent-class': 'GalilAxisControllerAgent',
   'instance-id': 'satcouplingoptics',
                 ['--ip', '10.120.1.6'],
                 ['--configfile', 'axes_config.yaml']]},
                 ['--mode', 'init'],



Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.

Galil Motor Axes Config
`````````````````````
A Galil controller configuration file defines the motion settings, motor
parameters, and brake mappings for each controlled axis. This allows the user
to easily adapt to different hardware configurations or coordinate multiple
axes (e.g., E and F) during operation::

   galil:
      motorsettings:
        maxspeed: 100000
        countspermm: 4000
        countsperdeg: 2000

      brakes:
        output_map:
          E: '5'
          F: '6'

      motorconfigparams:
        E:
          MT: '1'
          OE: '1'
          AG: '0'
          TL: '2'
          AU: '0'
        F:
          MT: '1'
          OE: '1'
          AG: '0'
          TL: '2'
          AU: '0'

      initaxisparams:
        BA: 'False'
        BM: '3276.8'
        BZ: '3'

      hold_limits:
        low: '<1000>'
        high: '1500'



Docker Compose
``````````````

The Galil Axis Controller Agent should be configured to run in a Docker container. An
example configuration is::

  ocs-galil-agent:
    image: simonsobs/socs:latest
    hostname: ocs-docker
    network_mode: "host"
    environment:
      - INSTANCE_ID=satcouplingoptics
      - SITE_HUB=ws://127.0.0.1:8001/ws
      - SITE_HTTP=http://127.0.0.1:8001/call
    volumes:
      - ${OCS_CONFIG_DIR}:/config:ro


Agent API
---------

.. autoclass:: socs.agents.galildmc_axis_controller.agent.GalilAxisControllerAgent
    :members:


