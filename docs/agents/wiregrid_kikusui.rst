.. highlight:: rst

.. _wiregrid_kikusui:

=======================
Wiregrid Kikusui Agent
=======================

The Wiregrid Kikusui Agent controls the wire-grid rotation.
The KIKUSUI is a power supply and
it is controlled via serial-to-ethernet converter.
The converter is linked to the KIKUSUI
via RS-232 (D-sub 9pin cable).
The agent communicates with the converter via Ethernet.

.. argparse::
   :filename: ../socs/agents/wiregrid_kikusui/agent.py
   :func: make_parser
   :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WiregridKikusuiAgent',
     'instance-id': 'wgkikusui',
     'arguments': [['--kikusui-ip', '10.10.10.71'],
                   ['--kikusui-port', '29'],
                   ['--encoder-agent', 'wgencoder']]},

- kikusui-ip is an IP address of the serial-to-ethernet converter.
- kikusui-port is an asigned port for the KIKUSUI power supply.
  (The converter has four D-sub ports to control
  multiple devices connected via serial communication.
  Communicating device is determined by the ethernet port number of the converter.)
- encoder-agent is an instance ID of the wiregrid encoder agent (wiregrid-encoder).
  This is necessary to get the position recorded by the encoder for controlling the rotation.

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-wgkikusui-agent:
      image: simonsobs/socs:latest
      hostname: ocs-docker
      network_mode: "host"
      command:
        - INSTANCE_ID=wgkikusui
      volumes:
        - ${OCS_CONFIG_DIR}:/config:ro
        - "<local directory to record log file>:/data/wg-data/action"

- Since the agent within the container needs to communicate with hardware on the
  host network you must use ``network_mode: "host"`` in your compose file.
- To control the wire-grid rotation accurately,
  the agent uses the OCS output of the ``Wiregrid Encoder Agent``.
- For the ``calibration_wg()`` function and debug mode (assigned by ``--debug`` option),
  a directory path to log files should be assigned in the ``volumes`` section
  (``/data/wg-data/action`` is the path in the docker).


Description
-----------

Functions
`````````

The agent has many functions, however most of them are for testing.
The main function is ``stepwise_rotation()``.

**Main Function (Stepwise Rotation)**
 - stepwise_rotation():
   Run step-wise rotation for wire-grid calibration.
   In each step, seveal small-rotations are occurred to rotate 22.5-deg.

**Continuous Rotation Funciton**
Nominally, the wire-grid calibration uses the above stepwise rotation.
However, if you want to rotate the wire-grid continuousely, you can use the following functions.
- set_c(): Set current [A]
- set_on(): Power ON the KIKUSUI power supply (start the rotation)
- set_off(): Power OFF the KIKUSUI power supply (stop the rotation)

**Optional Functions**
 - get_vc(): Show voltage [V], current [A], and ON/OFF
 - set_v(): Set voltage [V]
   (NOTE: Default motor voltage is 12 V. Thus, only 12 V is acceptable.)
 - get_angle(): Show wire-grid rotation angle obtained from encoder agent

**Calibration Function**
 - calibrate_wg(): Run rotation-motor calibration for the wire-grid.
   The output of this calibration is used to control the rotation in ``stepwire_rotation()``.
   This function repeats rotations several times and takes too long time (> hours).


Agent API
---------

.. autoclass:: socs.agents.wiregrid_kikusui.agent.WiregridKikusuiAgent
    :members:


Example Clients
---------------

Below is an example client to insert and eject the kikusui::

    from ocs.ocs_client import OCSClient
    wgkikusui = OCSClient('wgkikusui')

    # Set Voltage
    wgkikusui.set_v(volt=12.)

    # Set Current
    wgkikusui.set_c(current=3.)

    # Get voltage/current/onoff
    status, msg, session = wgkikusui.get_vc()
    print(session['messages'][1][1])

    # Stepwise rotation
    wgkikusui.stepwise_rotation(
        feedback_steps=8,
        num_laps=1,
        stopped_time=10.,
        )

    # Continuous rotation
    import time
    wgkikusui.set_on()
    time.sleep(10) #  10 sec rotation
    wgkikusui.set_off()
