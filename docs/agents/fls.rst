.. highlight:: rst

.. _fls:

=========
FLS Agent
=========

The Frequency-selectable Laser Source (FLS) is a calibrator that uses the
Toptica TeraScan 1550 laser system, installed in a setup with attenuating
prisms and mirrors. The calibrator is used for passband measurements with
detectors that are sensistive to 20 GHz - 1 THz frequencies.

.. argparse::
    :filename: ../socs/agents/fls/agent.py
    :func: ??
    :prog: python3 agent.py

Configuration File Examples
---------------------------

Below are configuration examples for the ocs config file and for running the
Agent in a docker container.

OCS Site Config
````````````````

To configure your FLS for use with OCS you need to add an FLSAgent block to 
your ocs configuration file. Here is an example configuration block::

  {'agent-class': 'FLSAgent',
   'instance-id': 'fls',
                 ['--ip', '169.254.18.24',
                  '--port', '1998',
                  '--mode', 'acq']}

Each device requires configuration under 'agent-instances'. See the OCS site
configs documentation for more details.


Example Clients and Procedures
------------------------------

Below are some example use cases for using this agent.

Starting up the FLS
```````````````````

.. note::
    All operations that require you to physically touch the instrument should
    be performed while wearing a grounding strap.

The startup procedure is as follows:

  1. At the back of the DLC Smart unit, manually flip the power switch. This
     will cause the unit to boot up, which will take about 1 minute. When the
     system is ready, it will produce a series of audible tones, and the
     light under "System Ready" on the front of the unit will flash green.
  2. Start the FLS Agent. This will initialize the connection. The DLC Smart
     unit will produce a series of audible tones, and the Agent will begin 
     data acquisition.
  3. To ensure that the voltage bias is set to zero::

       client.set_bias(bias='zero')

  4. Ensure that the U-shaped link is removed from the BNC breakout box,
     then turn on the lasers::

       client.toggle_laser_power(state='on')

     The white lights on top of the laser units will turn on if this operation
     is successful.

  5. Connect the PDA-S power supply to mains (i.e. by inserting the green 
     block connector into the PDA-S unit).
  6. Insert the U-shaped link into the BNC breakout box, closing the voltage
     bias line to the transmitter photomixer.
  7. Set the bias voltage to the default values::

       client.set_bias(bias='default')

Once this procedure is complete, the system is on and ready to use.

.. note::
    Although you can perform basic operations such as alignment with the system
    immediately after startup, the lasers will not reach full power until about
    1 hour after they are turned on. The frequency will also drift as the lasers
    warm up, so it is best to wait at least 36 hours from system startup to 
    make any scientific measurements.

Setting the laser frequency
```````````````````````````

To set the frequency of the lasers::

  client.set_frequency(frequency=100.0)

This will change the transmitter frequency. It will take a few seconds to reach
the correct frequency.

Running frequency sweeps
````````````````````````

Begin by setting the laser frequency to the frequency you want to start your
sweep at::

  client.set_frequency(frequency=120.0)

This Task concludes when the command is sent to the DLC Smart (not when the actual
frequency reaches the correct value). Then, start your frequency sweeps (i.e.
changing the frequency between two set endpoints)::

  client.run_frequency_sweeps.start(min_frequency=120.0,
                                    max_frequency=160.0,
                                    start_direction=1,
                                    frequency_step=0.05)

Here, :code:`min_frequency`, :code:`max_frequency`, and :code:`frequency_step` are
in units of GHz. :code:`start_direction` determines which direction the sweep will
go, where :code:`1` means that the laser frequency will increase during the sweep,
and :code:`-1` means that the laser frequency will decrease during the sweep.
:code:`num_of_sweeps` is an integer number of times that you want to sweep across
the frequency region, where the direction of the sweep will reverse each time (i.e.
if the first sweep has increasing frequency, the second sweep will have decreasing
frequency).

Shutting down the FLS
`````````````````````

.. note::
    All operations that require you to physically touch the instrument should
    be performed while wearing a grounding strap.

The shudtown procedure is as follows:

  1. Set the voltage bias to zero::

       client.set_bias(bias='zero')

  2. Put on a grounding strap. Remove the U-shaped link from the BNC Breakout Box.
  3. While wearing the grounding strap, disonnect the PDA-S power supply to mains
     (i.e. by removing the green block connector from the PDA-S unit).
  4. Turn off the lasers::

       client.toggle_laser_power(state='off')

  5. Stop the Agent from running.
  6. While wearing the grounding strap, turn off the DLC Smart using the power
     switch on the back of the instrument. 
