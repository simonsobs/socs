#!/usr/bin/env python3

# Author: zatkins, zhuber
# Acknowledgments: LS372 agent -- bkoopman, mhasselfield, jlashner

import argparse
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.Lakeshore.Lakeshore336 import LS336


class LS336_Agent:
    """Agent to connect to a single Lakeshore 336 device.
    Supports channels 'A','B','C', and 'D' for Lakeshore 336s that
    do not have the extra Lakeshore 3062 scanner installed. Also has
    channels 'D2','D3','D4', and 'D5' for 336s that have the extra
    scanner. Currently only supports heaters '1' and '2'.

    Parameters
    ----------

    sn: str
        Serial number of the LS336
    ip: str
        IP Address for the 336 device
    f_sample: float, optional (default 0.1)
        The frequency of sampling for acquiring data (in Hz)
    threshold: float, optional (default 0.1)
        The max difference (in K) between the setpoint and current
        temperature that will be considered stable
    window: int, optional (default 900)
        The amount of time (in s) over which the difference between the
        setpoint and the current temperature must not exceed threshold
        while checking for temperature stability.

    Attributes
    ----------
    sn: str
        Serial number of the LS336
    ip: str
        IP Address for the 336 device
    module: LS336 object
        Driver object
    module.channels: dict
        The available channels in the LS336 object
    module.heaters: dict
        The available heaters in the LS336 object
    f_sample: float
        The frequency of sampling for acquiring data (in Hz)
    t_sample: float
        The time between each sample (inverse of f_sample - 0.01)
    threshold: float
        The max difference (in K) between the setpoint and current temperature
        that will be considered stable
    window: int
        The amount of time (in s) over which the difference between the
        setpoint and the current temperature must not exceed threshold
        while checking for temperature stability.
    _recent_temps: numpy array, protected
        Array of recent temperatures for checking temperature stability
    _static_setpoint: float, protected
        The final setpoint value to avoid issues when the setpoint is
        ramping to a new value. Used in checking temperature stability
    """

    def __init__(self, agent, sn, ip, f_sample=0.1,
                 threshold=0.1, window=900):
        self.agent = agent
        self.sn = sn
        self.ip = ip
        self.f_sample = f_sample
        self.t_sample = 1 / self.f_sample - 0.01
        assert self.t_sample < 7200, \
            "acq sampling freq must be such that t_sample is less than 2 hours"

        self._lock = TimeoutLock()
        self.log = agent.log
        self.initialized = False
        self.take_data = False

        self.module = None

        # for stability checking
        self.threshold = threshold
        self.window = window
        self._recent_temps = None
        self._static_setpoint = None

        agg_params = {'frame_length': 10 * 60}  # sec

        # combined feed for thermometry and control data
        self.agent.register_feed(
            'temperatures',
            record=True,
            agg_params=agg_params,
            buffer_time=1
        )

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_lakeshore(self, session, params=None):
        """init_lakeshore(auto_acquire=False)

        **Task** - Perform first time setup of the Lakeshore 336 communication

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
        """
        if params is None:
            params = {}

        # test if this agent is already running
        if self.initialized:
            self.log.info('Lakeshore already initialized, returning...')
            return True, 'Already initialized'

        # initialize lakeshore
        with self._lock.acquire_timeout(job='init', timeout=0) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get lakeshore
            self.module = LS336(self.ip)
            session.add_message(
                f'Lakeshore initialized with ID: {self.module.id}')

        self.initialized = True

        # start data acq if passed
        if params.get('auto_acquire', False):
            self.agent.start('acq')

        return True, 'Lakeshore module initialized'

    @ocs_agent.param('f_sample', default=0.1, type=float)
    def acq(self, session, params=None):
        """acq(f_sample=0.1)

        **Process** - Begins recording data from thermometers and heaters.

        Parameters:
            f_sample (float, optional): Default is 0.1. Sets the
                sampling rate in Hz.

        Notes:
            The most recent data collected is stored in session.data in the
            structure:

               >>> response.session['data']
               {"ls336_fields":
                   {"timestamp": 1921920543,
                    "block_name": "temperatures"
                    "data": {"Channel_A_T": (some value)
                             "Channel_A_V": (some value)
                             "Channel_B_T": (some value)
                             "Channel_B_V": (some value)
                             "Channel_C_T": (some value)
                             "Channel_C_V": (some value)
                             "Channel_D_T": (some value)
                             "Channel_D_V": (some value)
                            }
                   }
               }
        """
        if params is None:
            params = {}

        # get sampling frequency
        f_sample = params.get('f_sample')
        if f_sample is None:
            t_sample = self.t_sample
        else:
            t_sample = 1 / f_sample - 0.01
            self.t_sample = t_sample

        # acquire lock and start Process
        with self._lock.acquire_timeout(job='acq', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # initialize recent temps array
            # shape is N_points x N_channels
            # N_points is 2 hour / t_sample rounded up
            # N_channels is 8 if the extra scanner is installed, 4 otherwise
            # t_sample can't be more than 2 hours
            N_channels = len(self.module.channels)
            self._recent_temps = np.full(
                (int(np.ceil(7200 / self.t_sample)), N_channels), -1.0)
            print(self._recent_temps.size)

            # acquire data from Lakeshore
            self.take_data = True
            while self.take_data:

                # get thermometry data
                current_time = time.time()
                temperatures_message = {
                    'timestamp': current_time,
                    'block_name': 'temperatures',
                    'data': {}
                }

                temps = self.module.get_kelvin('0')  # array of 4 (or 8) floats
                voltages = self.module.get_sensor('0')  # array of 4/8 floats
                for i, channel in enumerate(self.module.channels.values()):
                    channel_str = channel.input_name.replace(' ', '_')
                    temperatures_message['data'][channel_str + '_T'] = temps[i]
                    temperatures_message['data'][channel_str
                                                 + '_V'] = voltages[i]

                # append to recent temps array for temp stability check
                self._recent_temps = np.roll(self._recent_temps, 1, axis=0)
                self._recent_temps[0] = temps

                # publish to feed
                self.agent.publish_to_feed(
                    'temperatures', temperatures_message)

                # For session.data - named to avoid conflicting with LS372
                # if in use at same time.
                session.data['ls336_fields'] = temperatures_message

                # get heater data
                heaters_message = {
                    'timestamp': current_time,
                    'block_name': 'heaters',
                    'data': {}
                }

                for i, heater in enumerate(self.module.heaters.values()):
                    heater_str = heater.output_name.replace(' ', '_')
                    heaters_message['data'][
                        heater_str + '_Percent'] = heater.get_heater_percent()
                    heaters_message['data'][
                        heater_str + '_Range'] = heater.get_heater_range()
                    heaters_message['data'][
                        heater_str + '_Max_Current'] = heater.get_max_current()
                    heaters_message['data'][
                        heater_str + '_Setpoint'] = heater.get_setpoint()

                # publish to feed
                self.agent.publish_to_feed('temperatures', heaters_message)

                # finish sample
                self.log.debug(
                    f'Sleeping for {np.round(self.t_sample)} seconds...')

                # release and reacquire lock between data acquisition
                self._lock.release()
                time.sleep(t_sample)
                if not self._lock.acquire(timeout=10, job='acq'):
                    print(
                        f"Lock could not be acquired because it is held by "
                        f"{self._lock.job}")
                    return False, 'Could not re-acquire lock'

        return True, 'Acquisition exited cleanly'

    @ocs_agent.param('_')
    def stop_acq(self, session, params=None):
        """stop_acq()

        **Task** - Stops acq process.

        """
        if params is None:
            params = {}

        if self.take_data:
            self.take_data = False
            return True, 'Requested to stop taking data'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('range', type=str,
                     choices=['off', 'low', 'medium', 'high'])
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_heater_range(self, session, params):
        """set_heater_range(range=None,heater='2')

        **Task** - Adjusts the heater range for servoing the load.

        Parameters:
            range (str): Sets the range of the chosen heater. Must be one of
                         'off', 'low', 'medium', and 'high'.
            heater (str, optional): default '2'. Chooses which heater's range
                                    to change. Must be '1' or '2'.

        Notes:
            The range setting has no effect if an output is in the Off mode,
            and it does not apply to an output in Monitor Out mode. An output
            in Monitor Out mode is always on.
        """
        with self._lock.acquire_timeout(job='set_heater_range',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set range
            current_range = heater.get_heater_range()
            if params['range'] == current_range:
                print(
                    'Current heater range matches commanded value. '
                    'Proceeding unchanged')
            else:
                heater.set_heater_range(params['range'])

            session.add_message(
                f"Set {heater.output_name} range to {params['range']}")

        return True, f"Set {heater.output_name} range to {params['range']}"

    @ocs_agent.param('P', type=float, check=lambda x: 0.1 <= x <= 1000)
    @ocs_agent.param('I', type=float, check=lambda x: 0.1 <= x <= 1000)
    @ocs_agent.param('D', type=float, check=lambda x: 0 <= x <= 200)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_pid(self, session, params):
        """set_pid(P=None,I=None,D=None,heater='2')

        **Task** - Set the PID parameters for servoing the load.

        Parameters:
            P (float): Proportional term for PID loop (must be between
                       0.1 and 1000)
            I (float): Integral term for PID loop (must be between 0.1
                       and 1000)
            D (float): Derivative term for PID loop (must be between 0 and 200)
            heater (str, optional): Selects the heater on which to change
                                    the PID settings. Must be '1' or '2'.

        """
        with self._lock.acquire_timeout(job='set_pid', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set pid
            current_p, current_i, current_d = heater.get_pid()
            if (params['P'] == current_p
                    and params['I'] == current_i
                    and params['D'] == current_d):
                print('Current heater PID matches commanded value. '
                      'Proceeding unchanged')
            else:
                heater.set_pid(params['P'], params['I'], params['D'])

            session.add_message(
                f"Set {heater.output_name} PID to {params['P']}, "
                f"{params['I']}, {params['D']}")

        return True, (f"Set {heater.output_name} PID to {params['P']}, "
                      f" {params['I']}, {params['D']}")

    @ocs_agent.param('mode', type=str, choices=['off', 'closed loop', 'zone',
                                                'open loop'])
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_mode(self, session, params):
        """set_mode(mode=None,heater='2')

        **Task** - Sets the output mode of the heater.

        Parameters:
            mode (str): Selects the output mode for the heater.
                        Accepts four options: 'off', 'closed loop', 'zone',
                        and 'open loop'.
                        for restrictions based on the selected heater.
            heater (str, optional): Default '2'. Selects the heater on which
                                    to change the mode. Must be '1' or '2'.

        Notes:
            Does not support the options 'monitor out' and 'warm up',
            which only work for the unsupported analog outputs
            (heaters 3 and 4).
        """
        with self._lock.acquire_timeout(job='set_mode', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set mode
            current_mode = heater.get_mode()
            if params['mode'] == current_mode:
                print(
                    'Current heater mode matches commanded value. '
                    'Proceeding unchanged')
            else:
                heater.set_mode(params['mode'])

            session.add_message(
                f"Set {heater.output_name} mode to {params['mode']}")

        return True, f"Set {heater.output_name} mode to {params['mode']}"

    @ocs_agent.param('resistance', type=float)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_heater_resistance(self, session, params):
        """set_heater_resistance(resistance=None,heater='2')

        **Task** - Sets the heater resistance and resistance setting
        of the heater. The associated 'get' function in the Heater class
        is get_heater_resistance_setting().

        Parameters:
            resistance (float): The actual resistance of the load
            heater (str, optional): Default '2'. Selects the heater on which
                                    to set the resistance. Must be '1' or '2'.
        """
        with self._lock.acquire_timeout(job='set_heater_resistance',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set heater resistance
            _ = heater.get_heater_resistance_setting()
            if params['resistance'] == heater.resistance:
                print(
                    'Current heater resistance matches commanded value. '
                    'Proceeding unchanged')
            else:
                heater.set_heater_resistance(params['resistance'])

            session.add_message(
                f"Set {heater.output_name} resistance to "
                f"{params['resistance']}")

        return True, (f"Set {heater.output_name} resistance to "
                      f"{params['resistance']}")

    @ocs_agent.param('current', type=float, check=lambda x: 0.0 <= x <= 2.0)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_max_current(self, session, params):
        """set_max_current(current=None,heater='2')

        **Task** - Sets the maximum current that can pass through a heater.

        Parameters:
            current (float): The desired max current. Must be between
                             0 and 2 A.
            heater (str, optional): Default '2'. Selects the heater on which
                                    to set the max current. Must be '1' or '2'.
        """
        with self._lock.acquire_timeout(job='set_max_current',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set max current
            current_max_current = heater.get_max_current()
            if params['current'] == current_max_current:
                print(
                    'Current max current matches commanded value. '
                    'Proceeding unchanged')
            else:
                heater.set_max_current(params['current'])

            session.add_message(
                f"Set {heater.output_name} max current to {params['current']}")

        return True, (f"Set {heater.output_name} max current to "
                      f"{params['current']}")

    @ocs_agent.param('percent', type=float)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_manual_out(self, session, params):
        """set_manual_out(percent=None,heater='2')

        **Task** - Sets the manual output of the heater as a percentage of the
        full current or power depending on which display the heater
        is set to use.

        Parameters:
            percent (float): Percent of full current or power to set on the
                             heater. Must have 2 or fewer decimal places.
            heater (str, optional): Default '2'. Selects the heater on which
                                    to set the manual output.
                                    Must be '1' or '2'.
        """
        with self._lock.acquire_timeout(job='set_manual_out',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set manual out
            current_manual_out = heater.get_manual_out()
            if params['percent'] == current_manual_out:
                print('Current manual out matches commanded value. '
                      'Proceeding unchanged')
            else:
                heater.set_manual_out(params['percent'])

            session.add_message(
                f"Set {heater.output_name} manual out to {params['percent']}")

        return True, (f"Set {heater.output_name} manual out to "
                      f"{params['percent']}")

    @ocs_agent.param('input', type=str,
                     choices=['A', 'B', 'C', 'D', 'D1', 'D2', 'D3', 'D4', 'D5'])
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_input_channel(self, session, params):
        """set_input_channel(input=None,heater='2')

        **Task** - Sets the input channel of the heater control loop.

        Parameters:
            input (str): The name of the heater to use as the input channel.
                         Must be one of 'none','A','B','C', or 'D'.
                         Can also be 'D2','D3','D4', or 'D5' if the extra
                         Lakeshore 3062 Scanner is installed in your LS336.
            heater (str, optional): Default '2'. Selects the heater for which
                                    to set the input channel.
                                    Must be '1' or '2'.

        """
        with self._lock.acquire_timeout(job='set_input_channel',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # D1 is the same as D
            if params['input'] == 'D1':
                params['input'] = 'D'

            # set input channel
            current_input_channel = heater.get_input_channel()
            if params['input'] == current_input_channel:
                print(
                    'Current input channel matches commanded value. '
                    'Proceeding unchanged')
            else:
                heater.set_input_channel(params['input'])

            session.add_message(
                f"Set {heater.output_name} input channel to {params['input']}")

        return True, (f"Set {heater.output_name} input channel to "
                      f"{params['input']}")

    @ocs_agent.param('setpoint', type=float)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def set_setpoint(self, session, params):
        """set_setpoint(setpoint=None,heater='2')

        **Task** - Sets the setpoint of the heater control loop,
        after first turning ramp off. May be a limit to how high the setpoint
        can go based on your system parameters.

        Parameters:
            setpoint (float): The setpoint for the control loop. Units depend
                              on the preferred sensor units (Kelvin, Celsius,
                              or Sensor).
            heater (str, optional): Default '2'. Selects the heater for which
                                    to set the input channel.
                                    Must be '1' or '2'.
        """
        with self._lock.acquire_timeout(job='set_setpoint',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set setpoint
            current_setpoint = heater.get_setpoint()
            if params['setpoint'] == current_setpoint:
                print('Current setpoint matches commanded value. '
                      'Proceeding unchanged')
            else:
                heater.set_ramp_on_off('off')
                heater.set_setpoint(params['setpoint'])
                # static setpoint used in temp stability check
                # to avoid ramping bug
                self._static_setpoint = params['setpoint']

            session.add_message(
                f"Turned ramp off and set {heater.output_name} setpoint to "
                f"{params['setpoint']}")

        return True, (f"Turned ramp off and set {heater.output_name} "
                      f"setpoint to {params['setpoint']}")

    @ocs_agent.param('T_limit', type=int)
    @ocs_agent.param('channel', type=str, default='A',
                     choices=['A', 'B', 'C', 'D', 'D2', 'D3', 'D4', 'D5'])
    def set_T_limit(self, session, params):
        """set_T_limit(T_limit=None,channel='A')

        **Task** - Sets the temperature limit above which the control
                   output assigned to the selected channel shut off.

        Parameters:
            T_limit (int): The temperature limit in Kelvin. Note that a limit
                           of 0 K turns off this feature for the given channel.
            channel (str, optional): Default 'A'. Selects which channel to use
                                     for controlling the temperature. Options
                                     are 'A','B','C', and 'D'. Can also be
                                     'D2','D3','D4', or 'D5' if the extra
                                     Lakeshore 3062 Scanner is installed in
                                     your LS336.
        """
        with self._lock.acquire_timeout(job='set_T_limit',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get channel
            channel_key = params.get('channel', 'A')  # default to input A
            channel = self.module.channels[channel_key]

            # set T limit
            current_limit = channel.get_T_limit()
            if params['T_limit'] == current_limit:
                print('Current T limit matches commanded value. '
                      'Proceeding unchanged')
            else:
                channel.set_T_limit(params['T_limit'])

            session.add_message(
                f"Set {channel.input_name} T limit to {params['T_limit']}")

        return True, f"Set {channel.input_name} T limit to {params['T_limit']}"

    @ocs_agent.param('temperature', type=float)
    @ocs_agent.param('ramp', default=0.1, type=float)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    @ocs_agent.param('transport', default=False, type=bool)
    @ocs_agent.param('transport_offset', default=0, type=float,
                     check=lambda x: x >= 0.0)
    def servo_to_temperature(self, session, params):
        """servo_to_temperature(temperature=None,ramp=0.1,heater='2',\
                                transport=False,transport_offset=0)

        **Task** - A wrapper for setting the heater setpoint. Performs sanity
        checks on heater configuration before publishing setpoint:

            1. checks control mode of heater (closed loop)
            2. checks units of input channel (kelvin)
            3. resets setpoint to current temperature with ramp off
            4. sets ramp on to specified rate
            5. checks setpoint does not exceed input channel T_limit
            6. sets setpoint to commanded value

        Note that this function does NOT turn on the heater if it is off. You
        must use set_heater_range() to pick a range first.

        Parameters:
            temperature (float): The new setpoint in Kelvin. Make sure there is
                                 is a control input set to the heater and its
                                 units are Kelvin.
            ramp (float, optional): Default 0.1. The rate for how quickly
                                    the setpoint ramps to new value.
                                    Units of K/min.
            heater (str, optional): Default '2'. The heater to use
                                    for servoing. Must be '1' or '2'.
            transport (bool, optional): Default False. See Notes
                                        for description.
            transport_offset (float, optional): Default 0. In Kelvin.
                                                See Notes.

        Notes:
        If param 'transport' is provided and True, the control loop restarts
        when the setpoint is first reached. This is useful for loads with long
        cooling times or time constant to help minimize over/undershoot.

        If param 'transport' is provided and True, and 'transport_offset' is
        provided and positive, and the setpoint is higher than the
        current temperature, then the control loop will restart
        when the setpoint - transport_offset is first reached.
        This is useful to avoid  a "false positive"
        temperature stability check too shortly after transport completes.
        """
        # get sampling frequency
        t_sample = self.t_sample

        with self._lock.acquire_timeout(job='servo_to_temperature',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # get current setpoint
            current_setpoint = heater.get_setpoint()

            # check in correct control mode
            if heater.get_mode() != 'closed loop':
                session.add_message(
                    'Changing control to closed loop mode for servo.')
                heater.set_mode("closed loop")

            # check in correct units
            channel = heater.get_input_channel()
            if channel == 'none':
                return False, (f'{heater.output_name} does not have an '
                               f'input channel assigned')
            if self.module.channels[channel].get_units() != 'kelvin':
                session.add_message(
                    'Setting preferred units to kelvin on '
                    'heater control input.')
                self.module.channels[channel].set_units('kelvin')

            # restart setpoint at current temperature
            current_temp = np.round(float(self.module.get_kelvin(channel)), 4)
            session.add_message(
                f'Turning ramp off and setting setpoint to current '
                f'temperature {current_temp}')
            heater.set_ramp_on_off('off')
            heater.set_setpoint(current_temp)

            # reset ramp settings
            ramp = params.get('ramp', 0.1)
            session.add_message(
                f'Turning ramp on and setting rate to {ramp}K/min')
            heater.set_ramp_on_off('on')
            heater.set_ramp_rate(ramp)

            # make sure not exceeding channel T limit
            T_limit = self.module.channels[channel].get_T_limit()
            if T_limit <= params['temperature']:
                return False, (f"{heater.output_name} control channel "
                               f"{channel} T limit of {T_limit}K is lower "
                               f"than setpoint of {params['temperature']}")

            # set setpoint
            if params['temperature'] == current_setpoint:
                print('Current setpoint matches commanded value. '
                      'Proceeding unchanged')
            else:
                session.add_message(
                    f"Setting {heater.output_name} setpoint to "
                    f"{params['temperature']}")
                heater.set_setpoint(params['temperature'])
                # static setpoint used in temp stability check
                # to avoid pulling the ramping setpoint
                self._static_setpoint = params['temperature']

                # if transport, restart control loop when setpoint
                # first crossed
                if params.get('transport', False):

                    current_range = heater.get_heater_range()
                    starting_sign = np.sign(
                        params['temperature'] - current_temp)
                    transporting = True

                    # if we are raising temp, allow possibility of
                    # stopping transport at a cooler temp
                    T_offset = 0
                    if starting_sign > 0:
                        T_offset = params.get('transport_offset', 0)
                        if T_offset < 0:
                            return False, ('Transport offset temperature '
                                           'cannot be negative')

                    while transporting:
                        current_temp = np.round(
                            self.module.get_kelvin(channel), 4)
                        # check when this flips
                        current_sign = np.sign(
                            params['temperature'] - T_offset - current_temp)

                        # release and reacquire lock between data acquisition
                        self._lock.release()
                        time.sleep(t_sample)
                        if not self._lock.acquire(timeout=10,
                                                  job='servo_to_temperature'):
                            print(
                                f"Lock could not be acquired because it is "
                                f"held by {self._lock.job}")
                            return False, 'Could not re-acquire lock'

                        if current_sign != starting_sign:
                            transporting = False  # update flag

                            # cycle control loop
                            session.add_message(
                                'Transport complete, restarting control '
                                'loop at provided setpoint')
                            heater.set_heater_range('off')
                            # necessary 1 s for prev command to register
                            # in ls336 firmware for some reason
                            time.sleep(1)
                            heater.set_heater_range(current_range)

        return True, (f"Set {heater.output_name} setpoint to "
                      f"{params['temperature']}")

    @ocs_agent.param('threshold', default=0.1, type=float)
    @ocs_agent.param('window', default=900, type=int)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def check_temperature_stability(self, session, params):
        """check_temperature_stability(threshold=0.1,window=900,heater='2')

        **Task** - Assesses whether the load is stable around the setpoint
        to within some threshold.

        Parameters:
            threshold (float, optional): Default 0.1. See notes.
            window (int, optional): Default 900. See notes.
            heater (str, optional): Default '2'. Selects the heater for which
                                    to set the input channel.
                                    Must be '1' or '2'.

        Notes
        -----
        Param 'threshold' sets the upper bound on the absolute
        temperature difference between the setpoint and any temperature
        from the input channel in the last 'window' seconds.

        Param 'window' sets the lookback time into the most recent
        temperature data, in seconds. Note that this function grabs the most
        recent data in one window-length of time; it does not take new data.

        If you want to use the result of this task for making logical decisions
        in a client (e.g. waiting longer before starting a process if the
        temperature is not yet stable), use the session['success'] key. It will
        be True if the temperature is stable and False if not.
        Example:
        >>> response = ls336.check_temperature_stability()
        >>> response.session['success']
        True
        """

        # get threshold
        threshold = params.get('threshold')
        if threshold is None:
            threshold = self.threshold

        # get window
        window = params.get('window')
        if window is None:
            window = self.window
        num_idxs = int(np.ceil(window / self.t_sample))

        with self._lock.acquire_timeout(job='check_temperature_stability',
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # get channel
            channel = heater.get_input_channel()
            channel_num = self.module.channels[channel].num

            # get current temp
            current_temp = np.round(self.module.get_kelvin(channel), 4)

            # check if recent temps and current temps are within threshold
            _recent_temps = self._recent_temps[:num_idxs, channel_num - 1]
            _recent_temps = np.concatenate(
                (np.array([current_temp]), _recent_temps))

            # get static setpoint if None
            if self._static_setpoint is None:
                self._static_setpoint = heater.get_setpoint()

            # avoids checking against the ramping setpoint,
            # i.e. want to compare to commanded setpoint not mid-ramp setpoint
            setpoint = self._static_setpoint
            session.add_message(
                f'Maximum absolute difference in recent temps is '
                f'{np.max(np.abs(_recent_temps - setpoint))}K')

            if np.all(np.abs(_recent_temps - setpoint) < threshold):
                session.add_message(
                    f'Recent temps are within {threshold}K of setpoint')
                return True, (f'Servo temperature is stable within '
                              f'{threshold}K of setpoint')

        return False, (f'Servo temperature is not stable within '
                       f'{threshold}K of setpoint')

    @ocs_agent.param('attribute', type=str)
    @ocs_agent.param('channel', type=str, default='A',
                     choices=['A', 'B', 'C', 'D', 'D1', 'D2', 'D3', 'D4', 'D5'])
    def get_channel_attribute(self, session, params):
        """get_channel_attribute(attribute=None,channel='A')

        **Task** - Gets an arbitrary channel attribute and stores it in the
        session.data dict. Attribute must be the name of a method
        in the namespace of the Lakeshore336 Channel class,
        with a leading "get\\_" removed (see example).

        Parameters:
            attribute (str): The name of the channel attribute to get. See the
                             Lakeshore 336 Channel class API for all options.
            channel (str, optional): Default 'A'. Selects which channel for
                                     which to get the attribute. Options
                                     are 'A','B','C', and 'D'. Can also be
                                     'D2','D3','D4', or 'D5' if the extra
                                     Lakeshore 3062 Scanner is installed in
                                     your LS336.

        Example:
        >>> ls.get_channel_attribute(attribute = 'T_limit').session['data']
        {'T_limit': 30.0}
        """
        with self._lock.acquire_timeout(job=f"get_{params['attribute']}",
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get channel
            channel_key = params.get('channel', 'A')  # default to input A
            channel = self.module.channels[channel_key]

            # check that attribute is a valid channel method
            if getattr(channel, f"get_{params['attribute']}",
                       False) is not False:
                query = getattr(channel, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

        return True, (f"Retrieved {channel.input_name} {params['attribute']}, value is {resp}")

    @ocs_agent.param('attribute', type=str)
    @ocs_agent.param('heater', default='2', type=str, choices=['1', '2'])
    def get_heater_attribute(self, session, params):
        """get_heater_attribute(attribute=None,heater='2')

        **Task** - Gets an arbitrary heater attribute and stores it
        in the session.data dict. Attribute must be the name of a method
        in the namespace of the Lakeshore336 Heater class, with a leading
        "get\\_" removed (see example).

        Parameters:
            attribute (str): The name of the channel attribute to get. See the
                             Lakeshore 336 Heater class API for all options.
            heater (str, optional): Default '2'. Selects the heater for which
                                    to get the heater attribute.
                                    Must be '1' or '2'.

        Examples
        --------
        >>> ls.get_heater_attribute(attribute = 'heater_range').session['data']
        {'heater_range': 'off'}
        """
        with self._lock.acquire_timeout(job=f"get_{params['attribute']}",
                                        timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by "
                    f"{self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # check that attribute is a valid heater method
            if getattr(heater, f"get_{params['attribute']}",
                       False) is not False:
                query = getattr(heater, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

        return True, f"Retrieved {heater.output_name} {params['attribute']}, value is {resp}"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to
    automatically build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--ip-address', type=str,
                        help="IP address for the lakeshore")
    pgroup.add_argument('--f-sample', type=float, default=0.1,
                        help='The frequency of data acquisition')
    pgroup.add_argument('--threshold', type=float, default=0.1,
                        help='The upper bound on temperature differences '
                             'for stability check')
    pgroup.add_argument('--window', type=float, default=900.,
                        help='The lookback time on temperature differences '
                             'for stability check')
    pgroup.add_argument('--auto-acquire', type=bool, default=True,
                        help='Automatically start data acquisition on startup')
    return parser


def main(args=None):
    # Create an argument parser
    parser = make_parser()
    args = site_config.parse_args(agent_class='Lakeshore336Agent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested
    init_params = False
    if args.auto_acquire:
        init_params = {'auto_acquire': True}

    print('I am in charge of device with serial '
          'number: %s' % args.serial_number)

    # Create a session and a runner which communicate over WAMP
    agent, runner = ocs_agent.init_site_agent(args)

    # Pass the new agent session to the agent class
    lake_agent = LS336_Agent(agent, args.serial_number, args.ip_address,
                             args.f_sample, args.threshold, args.window)

    # Register tasks (name, agent_function)
    agent.register_task(
        'init_lakeshore', lake_agent.init_lakeshore, startup=init_params)
    agent.register_task('set_heater_range', lake_agent.set_heater_range)
    agent.register_task('set_heater_resistance',
                        lake_agent.set_heater_resistance)
    agent.register_task('set_input_channel', lake_agent.set_input_channel)
    agent.register_task('set_manual_out', lake_agent.set_manual_out)
    agent.register_task('set_max_current', lake_agent.set_max_current)
    agent.register_task('set_mode', lake_agent.set_mode)
    agent.register_task('set_pid', lake_agent.set_pid)
    agent.register_task('set_T_limit', lake_agent.set_T_limit)
    agent.register_task('set_setpoint', lake_agent.set_setpoint)
    agent.register_task('servo_to_temperature',
                        lake_agent.servo_to_temperature)
    agent.register_task('check_temperature_stability',
                        lake_agent.check_temperature_stability)
    agent.register_task('get_channel_attribute',
                        lake_agent.get_channel_attribute)
    agent.register_task('get_heater_attribute',
                        lake_agent.get_heater_attribute)

    # Register processes (name, agent_start_function, agent_end_function)
    agent.register_process('acq', lake_agent.acq, lake_agent.stop_acq)

    # Run the agent
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
