import argparse
import os
import time

import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.galil_axis.drivers import GalilAxis


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

    brakes = gal.get('brakes')
    if not isinstance(brakes, dict) or not brakes:
        raise ValueError("galil.brakes must be a non-empty dict of output map per axis.")

    motorsettings = gal.get('motorsettings')
    if not isinstance(motorsettings, dict) or not motorsettings:
        raise ValueError("galil.motorsettings must be a non-empty dict of mm/deg conversion values.")

    mparams = gal.get('motorconfigparams')
    if not isinstance(mparams, dict) or not mparams:
        raise ValueError("galil.motorconfigparams must be a non-empty dict of axes.")

    initparams = gal.get('initaxisparams')
    if not isinstance(initparams, dict) or not initparams:
        raise ValueError("galil.initaxisparams must be a non-empty dict of axes settings.")

    dwellparams = gal.get('dwell_times')
    if not isinstance(dwellparams, dict) or not dwellparams:
        raise ValueError("galil.dwell_times must be a non-empty dict of times for initializing axes.")

    return cfg


class GalilAxisAgent:
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
        self.first_dwell = None
        self.sec_dwell = None

        # Register data feeds
        agg_params = {
            'frame_length': 60,
        }

        self.agent.register_feed('stage_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('input_config', type=bool, default=False)
    @ocs_agent.param('auto_acquire', type=bool, default=False)
    def init(self, session, params=None):
        """init(input_config=False, auto_acquire=False)

        **Task** - Initalize connection to Galil axis controller.

        Parameters:
            input_config (bool, optional): If True, init task will also
                run `input_configfile` task as part of agent initialization.
                Defaults to False.
            auto_acquire(bool):  If True, start acquisition immediately after
                initialization. Defaults to False.

        """
        if self.initialized:
            return True, "Already initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because {self.lock.job}"
                              "is already running")
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
            self.first_dwell = gal['dwell_times']['first_ms']
            self.sec_dwell = gal['dwell_times']['second_ms']

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
        if params['input_config']:
            ok, msg = self.input_configfile(session, {'configfile': self.configfile})
            self.log.info(msg)
            if not ok:
                return False, f'Config load failed: {msg}'

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
                    {'E': {'position': 1182887.0, 'velocity': 0.0, 'torque': 0.0, 'position_error': 34.0},
                     'F': {'position': 5628.0, 'velocity': 0.0, 'torque': 0.0424, 'position_error': 23.0}},
                     'timestamp': 1761330944.879641}

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} is already running")
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            pm = Pacemaker(1 / 3, quantize=False)
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
                            'block_name': 'axes',
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
    @ocs_agent.param('movetype', type=str, choices=['linear', 'angular', 'encoder'])
    def set_relative_position(self, session, params):
        """set_relative_position(axis, distance, movetype)

        **Task** - Set the relative position location for a specified axis.

        Parameters:
            axis (str): Axis to command position. Ex: 'A'
            distance (float): Relative distance value, in millimeter, degrees,
                or raw counts, depending on `movetype`.
            movetype (str): 'linear' (mm) or 'angular' (deg), or 'encoder' for raw
                encoder counts.
        Notes:
            The conversion from millimeters to encoder counts is defined in the
            configuration file under `galil.motorsettings.countspermm` or
            `galil.motorsettings.countsperdeg`

        """
        axis = params['axis']
        distance = params['distance']
        movetype = params['movetype']
        with self.lock.acquire_timeout(timeout=5, job='set_relative_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Determine conversion factors
            if movetype == 'encoder':
                # use raw encoder units
                counts_per_unit = None
            elif movetype == 'linear':
                # use specific conversion factors
                counts_per_unit = self.counts_per_mm
            elif movetype == 'angular':
                counts_per_unit = self.counts_per_deg

            self.stage.set_relative_position(axis, distance,
                                             counts_per_unit=counts_per_unit)

        return True, f"Commanded {axis} to set to relative position: {distance}."

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('position', type=float)
    @ocs_agent.param('movetype', type=str, choices=['linear', 'angular', 'encoder'])
    def set_absolute_position(self, session, params):
        """set_absolute_position(axis, position, movetype)

        **Task** - Set the absolute position location for a specified axis.

        Parameters:
            axis (str): Axis to command position. Example: 'A'
            position (float): Absolute position distance value in mm, deg,
                or raw encoder counts.
            movetype (str): 'linear' (mm) or 'angular' (deg), or 'encoder' for raw
                encoder counts.

        Notes:
            The conversion from millimeters to encoder counts is defined in the
            configuration file under `galil.motorsettings.countspermm` or
            `galil.motorsettings.countsperdeg`
        """
        axis = params['axis']
        position = params['position']
        movetype = params['movetype']
        with self.lock.acquire_timeout(timeout=5, job='set_absolute_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Determine conversion factors
            if movetype == 'encoder':
                # use raw encoder units
                counts_per_unit = None
            elif movetype == 'linear':
                # use specific conversion factors
                counts_per_unit = self.counts_per_mm
            elif movetype == 'angular':
                counts_per_unit = self.counts_per_deg

            # Set the PA value
            self.stage.set_absolute_position(axis, position,
                                             counts_per_unit=counts_per_unit)

        return True, f"Commanded {axis} to set to absolute position: {position}"

    @ocs_agent.param('axis', type=str)
    def get_brake_status(self, session, params):
        """get_brake_status(axis)

        **Task** - Get brake status for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A', 'B').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_brake_status') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running")
                return False, "Could not acquire lock"
            
            output_num = self.brakes[axis]
            state, status = self.stage.get_brake_status(axis=axis, output_num=output_num)

        return True, f'Brake status for {axis} is {state}, {status}'

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

            if state == 'engage':
                self.stage.engage_brake(brake_outputnum)
            elif state == 'release':
                self.stage.release_brake(brake_outputnum)

        return True, f"Commanded the brake for axis {axis} to be set to {state}."

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

            status, msg = self.stage.begin_motion(axis)
            self.log.info(f'Status: {status}, {msg}')

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

        return True, f'Commanded motor type for {axis} to be set to {motortype}'

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

            resp = self.stage.get_motor_type(axis)

        return True, f"Motor type for axis {axis}: {resp}"

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
        with self.lock.acquire_timeout(timeout=5, job='set_off_on_error') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_off_on_error(axis, errtype)

        return True, f'Commanded the off-on-error for {axis} to be set to {errtype}.'

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

        return True, f'Commanded amp gain for {axis} to be set to {val}.'

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

        return True, f"Amplifier gain for {axis}: {resp}"

    @ocs_agent.param('axis', type=str)
    def get_amp_currentloop_gain(self, session, params):
        """get_amp_currentloop_gain(axis)

        **Task** - Query the amplifier current loop gain value for a given axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_amp_currentloop_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            resp = self.stage.get_amp_currentloop_gain(axis)

        return True, f"Amplifier current loop gain for {axis} is: {resp}."

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

        return True, f'Commanded amp current loop gain to be set to {val} for axis {axis}.'

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

        return True, f'Commanded torque limit for {axis} to be set to {val} volts'

    @ocs_agent.param('axis', type=str)
    def get_torque_limit(self, session, params):
        """get_torque_limit(axis)

        **Task** - Query motor torque limit for specified axis.

        Parameters:
            axis (str): Axis to query (e.g. 'A').
        """
        axis = params['axis']

        with self.lock.acquire_timeout(timeout=5, job='get_motor_state') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because {self.lock.job} is already running.")
                return False, "Could not acquire lock."

            resp = self.stage.get_torque_limit(axis)

        return True, f"Torque limit for axis {axis} is {resp}."

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

            self.stage.set_motor_state(axis, state)

        return True, f"Commanded motor {axis} to be {state}d."

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

        return True, f"Motor {axis} state: {human_state} (raw={state})"

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_magnetic_cycle(self, session, params):
        """set_magnetic_cycle(axis, val)

        **Task** - Set magnetic cycle value for motors with sinusoidal
            amplifiers for specific axis. Defines the length of the
            motor's magnetic cycle in encoder units.

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

        return True, f'Commanded magnetic cycle for {axis} to be set to {val}.'

    @ocs_agent.param('t_first', type=int)
    @ocs_agent.param('t_second', type=int)
    def set_dwell_times(self, session, params):
        """set_dwell_times(t_first, t_second)

        **Task** - Define dwell times for the initialization task to define
            the time for driving the motor to 2 different locations.

        Parameters:
            t_first (int): timing in milliseconds for driviing the motor to
                the first location. Ex: '1500'
            t_second (int): timing in milliseconds for driving the motor to
                the second location. Ex: '1000'

        """
        first = params['t_first']
        second = params['t_second']
        with self.lock.acquire_timeout(timeout=5, job='set_dwell_times') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_dwell_times(t_first=first, t_second=second)

        return True, f'Commanded dwell times for axes to be set to {first} and {second}ms, respectively.'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def initialize_axis(self, session, params):
        """initialize_axis(axis, val)

        **Task** - Initialize axes configured with sinusoidal amplifiers.
            During this procedure, each motor is driven to two magnetic
            positions to establish the commutation angle required for motion.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): Torque command voltage to be applied during initialization
            for axes that are configured for sinusoidal commutation. Ex: 3.0

        Notes:
            To run this task, you must run the `enable_sin_commutation`,
            `set_magnetic_cycle`, and `set_dwell_times` tasks first.

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='initialize_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.initialize_axis(axis, val)

        return True, f'Commanded {axis} to be initialized to {val} setting'

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

        return True, f'Commanded axis {axis} position to be set to {val}.'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('speed', type=float)
    def set_jog_speed(self, session, params):
        """set_jog_speed(axis, speed)

        **Task** - Defines the jog speed for the specified
            axis. Note that this task will set the speed to move
            the axis continuously when ready to begin motion,
            but does not begin motion.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            speed (float): The value of the speed in raw encoder units

        Notes:
            The speed value here is not defined in terms of millimeters or
            degrees. User will have to define in encoder counts
            (i.e., `4000` for 4000 counts/sec).

        """
        axis = params['axis']
        speed = params['speed']
        with self.lock.acquire_timeout(timeout=5, job='set_jog_speed') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_jog_speed(axis, speed)

        return True, f'Commanded {axis} jog speed to be set to {speed}.'

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('speed', type=float)
    def set_speed(self, session, params):
        """set_speed(axis, speed)

        **Task** - Sets the speed for a subsequent  motion/move-to command
        (such as relative or absolute position motion).

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
        with self.lock.acquire_timeout(timeout=5, job='set_speed') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_speed(axis, speed)

        return True, f'Commanded axis {axis} speed to be set to {speed}.'

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

        return True, f"Commanded sin commutation for axis {axis} to be enabled."

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

        return True, f'Commanded limit switch for {axis} to be disabled.'

    @ocs_agent.param('polarity', type=int)
    def set_limitswitch_polarity(self, session, params):
        """set_limitswitch_polarity(polarity)

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

        return True, f"Commanded limit switch polarity to be set to {pol}."

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

        return True, f'Commanded {axis} a to stop motion.'

    @ocs_agent.param('order', type=str)
    def set_gearing(self, session, params):
        """set_gearing(order)

        **Task** - Configure electronic gearing relationships between follower
            and leader axes.

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

        return True, f'Commanded gearing for leader/folower axes to be set to {order}.'

    @ocs_agent.param('order', type=str)
    def set_gearing_ratio(self, session, params):
        """set_gearing_ratio(order)

        **Task** - Set electronic gearing ratio between leader and follower axes.
            A ratio of 1 means the follower axis moves at the same speed as its
            leader axis.

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

        return True, f'Commanded gearing ratio for follower axes to be set to {order}.'

    @ocs_agent.param('axis', type=str)
    def get_gearing_ratio(self, session, params):
        """get_gearing_ratio(axis)

        **Task** - Query the current electronic gearing ratio for a specified axis

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

        return True, f"Gearing ratio for axis {axis} is: {resp}."

    @ocs_agent.param('configfile', type=str, default=None)
    def input_configfile(self, session, params=None):
        """input_configfile(configfile=None)

        **Task** Upload GalilDMC Axis Controller configuration file to initialize device
        and axes on device

        Parameters:
            configfile (str, optional):
                name of .yaml config file. Defaults to the file set in the site config.


        """
        configfile = params['configfile']
        if configfile is None:
            configfile = self.configfile
        if configfile is None:
            raise ValueError("No configfile specified")
        configfile = os.path.join(os.environ['OCS_CONFIG_DIR'], configfile)

        with self.lock.acquire_timeout(timeout=5, job='input_configfile') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            cfg = read_config(configfile)
            try:
                gal = cfg['galil']
                self.cfg = cfg
                self.motorsettings = gal['motorsettings']
                self.axis_map = gal['motorconfigparams']
                self.axes = list(self.axis_map.keys())
                self.brakes = gal['brakes']['output_map']
                self.first_dwell = gal['dwell_times']['first_ms']
                self.sec_dwell = gal['dwell_times']['second_ms']
            except Exception as e:
                return False, f'Config parse error: {e}'

            for a in self.axes:
                # set motor type
                self.stage.set_motor_type(axis=a, motortype=self.axis_map[a]['MT'])

                # set off on error
                self.stage.set_off_on_error(axis=a, errtype=self.axis_map[a]['OE'])

                # set amp gain
                self.stage.set_amp_gain(axis=a, val=self.axis_map[a]['AG'])

                # set torque limit
                self.stage.set_torque_limit(axis=a, val=self.axis_map[a]['TL'])

                # set current loop gain
                self.stage.set_amp_currentloop_gain(axis=a, val=self.axis_map[a]['AU'])

                # enable sin commutation
                initstate = gal['initaxisparams']['BA']
                if initstate == 'True':
                    # enable sin commutation
                    self.stage.enable_sin_commutation(axis=a)

                    # set magnetic cycle
                    self.stage.set_magnetic_cycle(axis=a, val=gal['initaxisparams']['BM'])

                    # set dwell times before initializing
                    self.stage.set_dwell_times(t_first=self.first_dwell, t_second=self.sec_dwell)

                    # initialize
                    self.stage.initialize_axis(axis=a, val=gal['initaxisparams']['BZ'])

        return True, "Commanded input_configfile task to set motor controller settings."


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
    pgroup.add_argument('--input_config', type=bool)
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='GalilAxisAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False,
                       'input_config': args.input_config}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True,
                       'input_config': args.input_config}

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    # create agent instance and run log creation
    galilaxis_agent = GalilAxisAgent(agent, args.ip, args.configfile)
    agent.register_task('init', galilaxis_agent.init, startup=init_params)
    agent.register_task('set_relative_position', galilaxis_agent.set_relative_position)
    agent.register_task('set_absolute_position', galilaxis_agent.set_absolute_position)
    agent.register_task('get_brake_status', galilaxis_agent.get_brake_status)
    agent.register_task('set_axis_brake', galilaxis_agent.set_axis_brake)
    agent.register_task('begin_axis_motion', galilaxis_agent.begin_axis_motion)
    agent.register_task('stop_axis_motion', galilaxis_agent.stop_axis_motion)
    agent.register_task('set_motor_type', galilaxis_agent.set_motor_type)
    agent.register_task('get_motor_type', galilaxis_agent.get_motor_type)
    agent.register_task('set_off_on_error', galilaxis_agent.set_off_on_error)
    agent.register_task('get_off_on_error', galilaxis_agent.get_off_on_error)
    agent.register_task('set_amp_gain', galilaxis_agent.set_amp_gain)
    agent.register_task('get_amp_gain', galilaxis_agent.get_amp_gain)
    agent.register_task('set_torque_limit', galilaxis_agent.set_torque_limit)
    agent.register_task('get_torque_limit', galilaxis_agent.get_torque_limit)
    agent.register_task('set_amp_currentloop_gain', galilaxis_agent.set_amp_currentloop_gain)
    agent.register_task('get_amp_currentloop_gain', galilaxis_agent.get_amp_currentloop_gain)
    agent.register_task('set_motor_state', galilaxis_agent.set_motor_state)
    agent.register_task('get_motor_state', galilaxis_agent.get_motor_state)
    agent.register_task('set_magnetic_cycle', galilaxis_agent.set_magnetic_cycle)
    agent.register_task('set_dwell_times', galilaxis_agent.set_dwell_times)
    agent.register_task('initialize_axis', galilaxis_agent.initialize_axis)
    agent.register_task('define_position', galilaxis_agent.define_position)
    agent.register_task('set_jog_speed', galilaxis_agent.set_jog_speed)
    agent.register_task('set_speed', galilaxis_agent.set_speed)
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
