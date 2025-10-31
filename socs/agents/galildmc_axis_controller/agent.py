import argparse
import os
import time

import numpy as np
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from twisted.internet import reactor

from socs.agents.galildmc_axis_controller.drivers import GalilAxis

# TODO: check jobs in each task to match name of task
# TODO Tasks: get_relative_position, get absolute position, get torque limit
# TODO: check input_configfile and if it needs to be updated
# TODO: safety checks when thinking about the positional error between two axes --> alarm? David?

if os.environ.get("GALIL_TEST_MODE"):
    from socs.agents.galildmc_axis_controller import drivers
    drivers.GalilAxis._drain_prompt = lambda self: b":"


def read_config(configfile):
    """ read and parse YAML config for axes.
    config file is str"""
    try:
        with open(configfile, 'r') as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        raise RuntimeError(f"Failed to read YAML '{configfile}': {e}")

    gal = cfg.get('galil')
    if not isinstance(gal, dict):
        raise ValueError("Config missing top-level 'galil' section.")

    mparams = gal.get('motorconfigparams')
    if not isinstance(mparams, dict) or not mparams:
        raise ValueError("galil.motorconfigparams must be a non-empty dict of axes.")

    return cfg


class GalilAxisControllerAgent:
    """ Agent for controlling Galil axis motors used in SAT
    coupling optics instrument for passband measurements on-site.

    Args:
        ip (str): IP address for the Galil axis motor controller
        configfile (str): Path to .yaml config file containing
            axis and motor settings
        port (int, optional): TCP port for controller communication.
            Default is 23
    """

    def __init__(self, agent, ip, configfile, port=23):
        self.lock = TimeoutLock()
        self.agent = agent
        self.log = agent.log
        self.ip = ip
        self.port = port
        self.configfile = configfile

        self.initialized = False
        self.take_data = False

        self.stage = None

        # Configuration state
        self.cfg = None
        self.motorsettings = None
        self.axis_map = None
        self.brakes = None
        self.axes = None
        self.counts_per_mm = None
        self.counts_per_deg = None

        # Register data feeds
        agg_params = {
            'frame_length': 60,
        }

        self.agent.register_feed('stage_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('configfile', type=str, default=None)
    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init(configfile=None, auto_acquire=False)

        **Task** - Initalize connection to Galil axis controller.

        Parameters:
            configfile (str, optional): Path to the .yaml configfile containing
                motor and axis settings. Defaults to None.
            auto_acquire(bool):  If True, start acquisition immediately after
                initialization. Defaults to False.

        """
        if self.initialized:
            return True, "Already initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              "{self.lock.job} is already running")
                return False, "Could not acquire lock."

            # Get axes from config file to establish connection to galil stage controller
            try:
                cfg = read_config(self.configfile)
            except Exception as e:
                return False, f'Config load failed: {e}. Could not start connection.'

            self.cfg = cfg
            gal = self.cfg['galil']
            self.axes = list(gal['motorconfigparams'].keys())
            self.counts_per_mm = gal['motorsettings']['countspermm']
            self.counts_per_deg = gal['motorsettings']['countsperdeg']
            self.brakes = gal['brakes']['output_map']

            # Establish connection
            self.stage = GalilAxis(ip=self.ip, port=self.port)

            # Test connection
            try:
                self.stage.get_data(self.axes)
            except ConnectionError:
                self.log.error("Could not establish connection to galil axis motor controller")
                return False, "Galil Axis Controller agent initialization failed"

        self.initialized = True

        # load configfile if provided as init argument
        if params.get('configfile'):
            ok, msg = self.input_configfile(session, {'configfile': params['configfile']})
            if not ok:
                return False, f'Config load failsed: {msg}'

        # start data acquistion if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Galil Axis Controller agent initialized"

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acquisition of data from the Galil Stage Controller.

        Parameters:
            test_mode (bool, optional): Run the process loop only once.
                This is meant only for testing. Default is False.

        Notes:
            The data collected is stored in session data in the structure::

                >> response.session['data']
                {'fields':
                    {'E': {'position': 1182887.0, 'velocity': 0.0, 'torque': 0.0, 'position_error': 34.0, 'gearing_ratio': 0.0},
                     'F': {'position': 5628.0, 'velocity': 0.0, 'torque': 0.0424, 'position_error': 23.0, 'gearing_ratio': 1.0}},
                     'timestamp': 1761330944.879641}

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} is already running")
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            pm = Pacemaker(0.2)  # , quantize=True)
            while self.take_data:
                pm.sleep()
                # Reliqinuish sampling lock occassionally
                if time.time() - last_release > 1:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                try:
                    data = self.stage.get_data(self.axes)
                    print('data', data)
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from galil stage controller. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue

                session.data = {"fields": data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'stage_status',
                            'data': {}}

                pub_data['data'] = data

                self.agent.publish_to_feed('stage_status', pub_data)

                if params['test_mode']:
                    break

        self.agent.feeds['stage_status'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('distance', type=float)
    @ocs_agent.param('movetype', type=str, choices=['linear', 'angular', None])
    @ocs_agent.param('encodeunits', type=bool, default=False)
    def set_relative_position(self, session, params):
        """set_relative_position(axis, lindist)

        **Task** - Set the relative position location for a specified axis.

        Parameters:
            axis (str): Axis to command position. Ex: 'A'
            distance (float): Relative distance value, in millimeter or degrees
                depending on `movetype`.
            movetype (str): 'linear' (mm) or 'angular' (deg), or `None` for raw
                encoder counts.
            encodeunits (bool): If True, interpret `distance` directly as raw counts
            instead of millimeters or degrees. Default is False.

        Notes:
            The conversion from millimeters to encoder counts is defined in the
            configuration file under `galil.motorsettings.countspermm` or
            `galil.motorsettings.countsperdeg`

        """
        axis = params['axis']
        distance = params['distance']
        movetype = params['movetype']
        encodeunits = params['encodeunits']
        with self.lock.acquire_timeout(0, job='set_relative_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Determine conversion factors
            if encodeunits and movetype is None:
                # use raw encoder units
                counts_per_unit = None
            elif not encodeunits and movetype is not None:
                # use specific conversion factors
                counts_per_units = (
                    self.counts_per_mm if movetype == 'linear' else self.counts_per_deg
                )

            self.stage.set_relative_position(axis, distance,
                                             counts_per_unit=counts_per_unit,
                                             encodeunits=encodeunits)

            self.log.info(f"Set relative {movetype} position for {axis}: {dist} "
                          f"{'encoder units' if encodeunits else 'mm'}")

        return True, f"Axis {axis} set to relative position: {distance}."

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('position', type=float)
    @ocs_agent.param('movetype', type=str, choices=['linear', 'angular', None])
    @ocs_agent.param('encodeunits', type=bool, default=False)
    def set_absolute_position(self, session, params):
        """set_absolute_position(axis, position, movetype='linear', encodeunits=False)

        **Task** - Set the absolute position location for a specified axis.

        Parameters:
            axis (str): Axis to command position. Example: 'A'
            position (float): Absolute position distance value in mm, deg,
                or raw encoder counts.
            movetype (str): 'linear' (mm) or 'angular' (deg), or `None` for raw
                encoder counts.
            encodeunits (bool): If True, interpret `distance` directly as raw counts
            instead of millimeters or degrees. Default is False.

        """
        axis = params['axis']
        position = params['position']
        movetype = params['movetype']
        encodeunits = params['encodeunits']

        with self.lock.acquire_timeout(0, job='set_absolute_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Determine conversion factors
            if encodeunits and movetype is None:
                # use raw encoder units
                counts_per_unit = None
            elif not encodueunits and movetype is not None:
                # use specific conversion factors
                counts_per_units = (
                    self.counts_per_mm if movetype == 'linear' else self.counts_per_deg
                )

            # Set the PA value
            self.stage.set_absolute_position(axis, position,
                                             counts_per_unit=counts_per_unit,
                                             encodeunits=encodeunits)

            self.log.info(f"Set absolute {movetype} position for axis {axis}: "
                          f"{position} {'encoder units' if encodeunits else movetype}")

        return True, f"Axis {axis} set to absolute position: {distance}"

    @ocs_agent.param('axis', type=str)
    def get_brake_status(self, session, params):
        """get_brake_status(axis)

        **Task** - Get brake status for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=3, job='get_brake_status') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running")
                return False, "Could not acquire lock"

            response = self.stage.get_brake_status(axis=axis, output_map=self.brakes)
            session.log.info(f'Brake status for {axis} is: {response}')

        return True, f'Brake status for {axis} is: {response}'

    @ocs_agent.param('axis', type=str)
    def get_motor_state(self, session, params):
        """get_motor_state()

        **Task** - Check if an axis motor is enabled.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B').
        """
        with self.lock.acquire_timeout(timeout=3, job='get_motor_state') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            response = self.stage.get_motor_state(axis=axis)
            session.log.info(f'Motor state is: {response}')

        return True, f'Motor state is: {response}'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('state', type=str, choices=['engage', 'release'])
    def set_axis_brake(self, session, params):
        """set_axis_brake(axis, state)

        **Task** - Engages or releases the brake for the specified axis.

        Parameters:
            axis (str): Axis to control brake for. Ex. 'A'
            state (str): Desired brake state — 'engage' or 'release'.
        """
        axis = params['axis']
        state = params['state'].lower()

        with self.lock.acquire_timeout(timeout=5, job='set_axis_brake') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            brake_outputnum = self.brakes[axis]

            try:
                if state == 'engage':
                    self.stage.engage_brake(brake_outputnum)
                elif state == 'release':
                    self.stage.release_brake(brake_outputnum)
                else:
                    return False, f"Invalid brake state '{state}'. Must be 'engage' or 'release'."
            except Exception as e:
                self.log.error(f"Failed to {state} brake for {axis}-axis: {e}")
                return False, f"Error during brake {state}: {e}"

        return True, f"Set brake status to: {state}."

    @ocs_agent.param('axis', type=str)
    def begin_axis_motion(self, session, params):
        """begin_axis_motion(axis)

        **Task** - Moves the specified axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='begin_axis_motion') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.begin_motion(axis)
            self.log.info(f'Now moving {axis}')

        return True, f'Commanded {axis} to move.'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('motortype', type=int)
    def set_motor_type(self, session, params):
        """set_motor_type(axis)

        **Task** - Sets motor type for each axis, depending on servo motor features

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        motortype = params['motortype']
        with self.lock.acquire_timeout(timeout=5, job='set_motor_type') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_motor_type(axis, motortype)

        return True, f'Motor type for {axis} set to {motortype}'

    @ocs_agent.param('axis', type=str)
    def get_motor_type(self, session, params):
        """get_motor_type(axis)

        **Task** - Queries the motor type for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_motor_type') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            try:
                resp = self.stage.get_motor_type(axis)
                self.log.info(f"Motor type for axis {axis}: {resp}")
            except Exception as e:
                self.log.error(f"Failed to query motor type for {axis}: {e}")
                return False, f"Error querying motor type for {axis}: {e}"

        return True, f"Motor type for {axis}: {resp}"

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('errtype', type=int)
    def set_off_on_error(self, session, params):
        """set_off_on_error(axis)

        **Task** - Configure the off-on-error behavior for a specified axis.

        This task enables or disables the Galil controller's off-on-error function,
        which determines whether the motor power is shut off when a position error
        occurs.

        Parameters:
            axis (str): Axis to configure. Ex. 'A'
            errtype(int):  Error handling mode, as defined by the controller’s
                disable/enable settings.

        """
        axis = params['axis']
        errtype = params['errtype']
        with self.lock.acquire_timeout(timeout=3, job='set_off_on_error') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_off_on_error(axis, errtype)

        return True, f'Off-on-error for {axis} is set to {errtype}'

    @ocs_agent.param('axis', type=str)
    def get_off_on_error(self, session, params):
        """get_off_on_error(axis)

        **Task** - Query the Off-On-Error (OE) state for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B', 'E').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_off_on_error') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            raw_val, human_state = self.stage.get_off_on_error(axis)
            self.log.info(f"OE for {axis}: {human_state} (raw={raw_val})")

        return True, f"OE for {axis}: {human_state} (raw={raw_val})"

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=int)
    def set_amp_gain(self, session, params):
        """set_amp_gain(axis, val)

        **Task** - Set amplifier gain for internal amplifier per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (int): Amplifier gain value to apply, as defined by
                controller's internal gain settings

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_amp_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_amp_gain(axis, val)

        return True, f'Amp gain for {axis} set to {val}'

    @ocs_agent.param('axis', type=str)
    def get_amp_gain(self, session, params):
        """get_amp_gain(axis)

        **Task** - Query the amplifier gain value for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B', 'E').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_amp_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            resp = self.stage.get_amp_gain(axis)
            self.log.info(f"Amplifier gain for {axis}: {resp}")

        return True, f"Amplifer Gain for {axis}: {resp}"

    @ocs_agent.param('axis', type=str)
    def get_amp_currentloop_gain(self, session, params):
        """get_amp_currentloop_gain(axis)

        **Task** - Query the amplifier current loop gain value for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B', 'E').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_amp_currentloop_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            resp = self.stage.get_amp_currentloop_gain(axis)

        return True, f"Amplifer Current Loop Gain for {axis}: {resp}"

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_torque_limit(self, session, params):
        """set_torque_limit(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): Torque limit value in volts. Defines max
            allowable motor current, as specifiied by controller's
            internal settings.

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_torque_limit') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_torque_limit(axis, val)

        return True, f'Torque limit for {axis} set to {val} volts'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=int)
    def set_amp_currentloop_gain(self, session, params):
        """set_amp_currentloop_gain(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (int): Current-loop gain value to apply.

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_amp_currentloop_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_amp_currentloop_gain(axis, val)

        return True, f'Amp current loop gain set to {val} for axis {axis}'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('state', type=str, choices=['enable', 'disable'])
    def set_motor_state(self, session, params):
        """set_motor_state(axis, state)

        **Task** - Enable or disable axis motor, and query its state.

        Parameters:
            axis (str): Axis to set motor state for (e.g. 'A', 'B', 'E').
            state (str): Desired motor state — 'enable' or 'disable'.
        """
        axis = params['axis']
        state = params['state']

        with self.lock.acquire_timeout(timeout=5, job='set_motor_state') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            status, human_state = self.stage.set_motor_state(axis, state)

        return True, f"Motor {axis} {state}d; verified state: {human_state} (raw={status})"

    @ocs_agent.param('axis', type=str)
    def get_motor_state(self, session, params):
        """get_motor_state(axis)

        **Task** - Query and interpret whether a motor is ON or OFF for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_motor_state') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            state, human_state = self.stage.get_motor_state(axis)
            self.log.info(f"Motor {axis} state: {human_state} (raw={state})")

        return True, f"Motor {axis} state: {human_state} (raw={state})"

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_magnetic_cycle(self, session, params):
        """set_magnetic_cycle(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): Magnetic cycle value to apply.

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_magnetic_cycle') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_magnetic_cycle(axis, val)

        return True, f'Magnetic cycle for {axis} set to {val}'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def initialize_axis(self, session, params):
        """initialize_axis(axis, val)

        **Task** - Initialize axes for sinusoidal amplifier settings..

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): Torque command voltage to be applied during initialization
            for axes that are configured for sinusoidal commutation.

        Notes:
            To run this task, you must run the `enable_sin_commutation` and
            the `set_magnetic_cycle` tasks first.

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='initialize_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.initialize_axis(axis, val)

        return True, f'Initialized {axis} to {val} setting'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def define_position(self, session, params):
        """define_position(axis, val)

        **Task** - Resets the position of an axis encoder to a specifically
            set value.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): The value to set the current motor position as specified by user.
                (i.e., 0.00 if homing)

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='define_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.define_position(axis, val)

        return True, f'{axis} position now set to {val}'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('speed', type=float)
    def jog_axis(self, session, params):
        """jog_axis(axis, val)

        **Task** - Sets the jog mode and the jog speed fo the axes,
        moving the axis continuously at the commanded speed.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            speed (float): Specified speed value in raw encoder units

        Notes:
            The speed value here is not defined in terms of millimeters or
            degrees. User will have to define in encoder counts
            (i.e., `4000` for 4000 counts/sec).

        """
        axis = params['axis']
        speed = params['speed']
        with self.lock.acquire_timeout(timeout=5, job='jog_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.jog_axis(axis, speed)

        return True, f'{axis} speed is now set to {speed}'

    @ocs_agent.param('axis', type=str)
    def enable_sin_commutation(self, session, params):
        """enable_sin_commutation(axis)

        **Task** -  Enable sinusoidal commutation for a specified brushless axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='enable_sin_commutation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.enable_sin_commutation(axis)
            self.log.info(f'Sin commutation setting for {axis} is enabled.')

        return True

    @ocs_agent.param('axis', type=str)
    def disable_limit_switch(self, session, params):
        """disable_limit_switch(axis)

        **Task** - Disable the hardware limit switch for a specified axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='disable_limit_switch') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.disable_limit_switch(axis)
            self.log.info(f'Limit switch for {axis} is disabled.')

        return True, f'Limit switch for {axis} is disabled.'

    @ocs_agent.param('polarity', type=int)
    def set_limitswitch_polarity(self, session, params):
        """set_limitswitch_polarity()

        **Task** - Configure the limit switch polarity for all axes.

        Parameters:
            polarity (int): Limit switch polarity value.
                0 is active-low (limit triggers when input goes low),
                1 is active-high (limit triggers when input goes high).

        """
        pol = params['polarity']
        with self.lock.acquire_timeout(timeout=5, job='set_limitswitch_polarity') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_limitswitch_polarity(pol)
            self.log.info(f'Limit switch polarity for {axis} is set to {pol}.')

        return True

    @ocs_agent.param('axis', type=str)
    def stop_axis_motion(self, session, params):
        """stop_axis_motion()

        **Task** - Stop motion for specified axis.

        Parameters:
              axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='stop_axis_motion') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.stop_motion(axis)

        return True, f'Stopped motion for {axis}.'

    @ocs_agent.param('order', type=str)
    def set_gearing(self, session, params):
        """set_gearing(order)

        **Task** - Configure electronic gearing relationships between axes..

        Parameters:
            order (str): Comma-separated axis assignment string defining the leader/
            follower mapping (e.g., (',,,,,E' assigns E as the leader for F axis).

        """
        order = params['order']
        with self.lock.acquire_timeout(timeout=5, job='set_gearing') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_gearing(order)

        return True, f'Gearing set to {order}'

    @ocs_agent.param('order', type=str)
    def set_gearing_ratio(self, session, params):
        """set_gearing_ratio(order)

        **Task** - Set electronic gearing ratio between leader and follower axes.

        Parameters:
            order (str): Comma-separated string of gearing ratios for each axis,
            similar in format as `set_gearing` task.  Example: ',,,,,1' sets a ratio
            of 1 between the F follower and E leader axes, meaning F follows
            E at the same speed.

        """
        order = params['order']
        with self.lock.acquire_timeout(timeout=5, job='set_gearing_ratio') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_gearing_ratio(order)

        return True, f'Gearing ratio set to {order}'

    @ocs_agent.param('axis', type=str)
    def get_gearing_ratio(self, session, params):
        """get_gearing_ratio(order)

        **Task** - Query the current electronig gearing ratio for a specified axis

        Parameters:
            axis (str): Axis to query (e.g., 'A')

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='get_gearing_ratio') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            resp = self.stage.get_gearing_ratio(axis=axis)

        return True, f'Gearing ratio for axis {axis} is {resp}'

    @ocs_agent.param('configfile', type=str, default=None)
    def input_configfile(self, session, params=None):
        """input_configfile(configfile=None)

        **Task** Upload GalilDMC Axis Controller configuration file to initialize device
        and axes on device

        Parameters:
            configfile (str, optional):
                name of .yaml config file. Defaults to the fite set in the site config


        """
        configfile = params['configfile']
        if configfile is None:
            configfile = self.configfile
        if configfile is None:
            raise ValueError("No configfile specified")
        configfile = os.path.join(os.environ['OCS_CONFIG_DIR'], configfile)

        with self.lock.acquire_timeout(job='input_configfile') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            cfg = read_config(configfile)
            try:
                gal = cfg.get('galil', {})
                self.cfg = cfg
                self.motorsettings = gal.get('motorsettings', {})
                self.axis_map = gal.get('motorconfigparams', {})
                self.axes = list(self.axis_map.keys())
                self.brakes = gal['brakes']['output_map']
            except Exception as e:
                return False, f'Config parse error: {e}'

            for a in axes:
                # set motor type
                motortype = config['galil']['motorconfigparams'][a]['MT']
                self.stage.set_motor_type(axis=a, motortype=motortype)

                # set off on error
                errtype = config['galil']['motorconfigparams'][a]['OE']
                errtype = int(errtype)
                self.stage.set_off_on_error(axis=a, errtype=errtype)

                # set amp gain
                gn = config['galil']['motorconfigparams'][a]['AG']
                self.stage.set_amp_gain(axis=a, val=gn)

                # set torque limit
                tl = config['galil']['motorconfigparams'][a]['TL']
                self.stage.set_torque_limitn(axis=a, val=tl)

                # set current loop gain
                clgn = config['galil']['motorconfigparams'][a]['AU']
                self.stage.set_amp_currentloop_gain(axis=a, val=clgn)

                # enable sin commutation
                initstate = gal['initaxisparams']['BA']
                if initstate == 'True':
                    # enable sin commutation
                    self.stage.enable_sin_commutation(axis=a)
                    # set magnetic cycle
                    mag = gal['initaxisparams']['BM']
                    self.stage.set_magnetic_cycle(axis=a, val=mag)
                    # initialize
                    val == gal['initaxisparams']['BZ']
                    self.stage.initialize_axis(axis=a, val=val)


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automaticall build documenation based on this function.


    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip')
    pgroup.add_argument('--port', default=23)
    pgroup.add_argument('--configfile')
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='GalilAxisControllerAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    # create agent instance and run log creation
    galilaxis_agent = GalilAxisControllerAgent(agent, args.ip, args.configfile)
    agent.register_task('init', galilaxis_agent.init, startup=init_params)
    agent.register_task('set_relative_position', galilaxis_agent.set_relative_position)
    agent.register_task('set_absolute_position', galilaxis_agent.set_absolute_position)
    agent.register_task('get_brake_status', galilaxis_agent.get_brake_status)
    agent.register_task('set_axis_brake', galilaxis_agent.set_axis_brake)
    agent.register_task('begin_axis_motion', galilaxis_agent.begin_axis_motion)
    agent.register_task('stop_axis_motion', galilaxis_agent.stop_axis_motion)
    agent.register_task('set_motor_type', galilaxis_agent.set_motor_type)
    agent.register_task('get_motor_type', galilaxis_agent.get_motor_type)
    agent.register_task('get_motor_state', galilaxis_agent.get_motor_state)
    agent.register_task('set_motor_state', galilaxis_agent.set_motor_state)
    agent.register_task('set_off_on_error', galilaxis_agent.set_off_on_error)
    agent.register_task('get_off_on_error', galilaxis_agent.get_off_on_error)
    agent.register_task('set_amp_gain', galilaxis_agent.set_amp_gain)
    agent.register_task('get_amp_gain', galilaxis_agent.get_amp_gain)
    agent.register_task('set_torque_limit', galilaxis_agent.set_torque_limit)
    agent.register_task('set_amp_currentloop_gain', galilaxis_agent.set_amp_currentloop_gain)
    agent.register_task('get_amp_currentloop_gain', galilaxis_agent.get_amp_currentloop_gain)
    agent.register_task('set_motor_state', galilaxis_agent.set_motor_state)
    agent.register_task('get_motor_state', galilaxis_agent.get_motor_state)
    agent.register_task('set_magnetic_cycle', galilaxis_agent.set_magnetic_cycle)
    agent.register_task('initialize_axis', galilaxis_agent.initialize_axis)
    agent.register_task('define_position', galilaxis_agent.define_position)
    agent.register_task('jog_axis', galilaxis_agent.jog_axis)
    agent.register_task('enable_sin_commutation', galilaxis_agent.enable_sin_commutation)
    agent.register_task('disable_limit_switch', galilaxis_agent.disable_limit_switch)
    agent.register_task('set_limitswitch_polarity', galilaxis_agent.set_limitswitch_polarity)
    agent.register_task('set_gearing', galilaxis_agent.set_gearing)
    agent.register_task('set_gearing_ratio', galilaxis_agent.set_gearing_ratio)
    agent.register_task('get_gearing_ratio', galilaxis_agent.get_gearing_ratio)
    agent.register_task('input_configfile', galilaxis_agent.input_configfile)
    agent.register_process('acq', galilaxis_agent.acq, galilaxis_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
