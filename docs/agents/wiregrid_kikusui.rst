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
The agent communicates with the converter via eternet.

.. argparse::
   :filename: ../agents/wiregrid_kikusui/kikusui_agent.py
   :func: make_parser
   :prog: python3 kikusui_agent.py

Dependencies
------------

This agent depends on src/command.py, moxaSerial.py, and pmx.py.
These scripts are also used in hwp_rotation agent.
Therefore, they should be shared.


Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

An example site-config-file block::

    {'agent-class': 'WGKIKUSUIAgent',
     'instance-id': 'wgkikusui',
     'arguments': [['--kikusui-ip', '10.10.10.71'],
                   ['--kikusui-port', '29']]},

- kikusui-ip is an IP address of the serial-to-ethernet converter.
- kikusui-port is an asigned port for the KIKUSUI power supply.
  (The converter has four D-sub ports to control
  multiple devices connected via serial communication.
  Communicating device is determined by the ethernet port number of the converter.)

Docker Compose
``````````````

An example docker-compose configuration::

    ocs-wgkikusui-agent:
      image: simonsobs/ocs-wgkikusui-agent:latest
      restart: always
      hostname: kyoto-docker
      network_mode: "host"
      depends_on:
        - "crossbar"
      volumes_from:
        - ocs-wgencoder-agent
      command:
        - "--instance-id=wgkikusui"

- Since the agent within the container needs to communicate with hardware on the
  host network you must use ``network_mode: "host"`` in your compose file.
- To control the wire-grid rotation accurately, 
  the agent uses the output of the ``Wiregrid Encoder Agent``.
  Therefore, mounting the volume of the ``ocs-wgencoder-agent`` is necessary. 


Description
-----------

Functions
`````````

The agent have many functions, however most of them are for a test.
The main function is ``stepwise_rotation()``.
``calibrate_wg()``.

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
   
**Calibration Function**
 - calibrate_wg(): Run rotation-motor calibration for the wire-grid.
   The output of this calibration is used to control the rotation in ``stepwire_rotation()``.
   This function repeats rotations several times and takes too long time (> hours).


Agent API
---------

.. autoclass:: agents.wiregrid_kikusui.kikusui_agent.KikusuiAgent
    :members:


Example Clients
---------------

Below is an example client to insert and eject the kikusui::

    from ocs import matched_client
    wgkikusui = matched_client.MatchedClient('wgkikusui', args=[])

    # Set Voltage
    wgkikusui.set_v.start(volt=12.)
    wgkikusui.set_v.wait()

    # Set Current
    wgkikusui.set_c.start(current=3.)
    wgkikusui.set_c.wait()

    # Get voltage/current/onoff
    wgkikusui.get_vc.start()
    status, msg, session = wgkikusui.get_vc.wait()
    print(session['messages'][1][1])

    # Stepwise rotation
    wgkikusui.stepwise_rotation.start(
        feedback_steps=8,
        num_laps=1,
        stopped_time=10.,
        )
    wgkikusui.stepwise_rotation.wait()

    # Continuous rotation
    import time
    wgkikusui.set_on.start()
    wgkikusui.set_on.wait()
    time.sleep(10) #  10 sec rotation
    wgkikusui.set_off.start()
    wgkikusui.set_off.wait()
