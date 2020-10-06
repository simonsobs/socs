#!/usr/bin/env python3

# author: zatkins
# acknowledgments: LS372 agent -- bkoopman, mhasselfield, jlashner

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.Lakeshore.Lakeshore336 import LS336

import numpy as np
import argparse
import time


class LS336_Agent:

    def __init__(self, agent, sn, port, f_sample=0.1, wait=1, threshold=0.1, window=900):
        self.agent = agent
        self.sn = sn
        self.port = port
        self.f_sample = f_sample
        self.t_sample = 1/self.f_sample - 0.01
        assert self.t_sample < 7200, \
            "acq sampling freq must be such that t_sample is less than 2 hours"

        self.lock = TimeoutLock()
        self.log = agent.log
        self.initialized = False
        self.take_data = False

        self.module = None
        self.wait = wait

        # for stability checking
        self.threshold = threshold
        self.window = window
        self.recent_temps = None
        self.static_setpoint = None

        agg_params = {'frame_length': 10*60}  # sec

        # combined feed for thermometry and control data
        self.agent.register_feed(
            'temperatures',
            record=True,
            agg_params=agg_params,
            buffer_time=1
        )

    def init_lakeshore_task(self, session, params=None):
        """Initialize the physical lakeshore module

        Parameters
        ----------
        params : dict, optional
            Contains optional parameters passed at Agent instantiation, by default None.
            Only parameter here is auto_acquire, by default False.
        """
        if params is None:
            params = {}

        # test if this agent is already running
        if self.initialized:
            self.log.info('Lakeshore already initialized, returning...')
            return True, 'Already initialized'

        # initialize lakeshore
        with self.lock.acquire_timeout(job='init', timeout=0) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get lakeshore
            self.module = LS336(self.port)
            session.add_message(
                f'Lakeshore initialized with ID: {self.module.id}')

        self.initialized = True

        # start data acq if passed
        if params.get('auto_acquire', False):
            self.agent.start('acq')

        return True, 'Lakeshore module initialized'

    def start_acq(self, session, params=None):
        """Begins recording of data to frames.

        Parameters
        ----------
        params : dict, optional
            Contains optional parameters passed at Agent instantiation, by default None.
            Only parameter is 'f_sample', by default 0.1.
        """
        if params is None:
            params = {}

        # get sampling frequency
        f_sample = params.get('f_sample')
        if f_sample is None:
            t_sample = self.t_sample
        else:
            t_sample = 1/f_sample - 0.01
            self.t_sample = t_sample

        # acquire lock and start Process
        with self.lock.acquire_timeout(job='acq', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # initialize recent temps array
            # shape is N_points x 4, where N_points is 2 hour / t_sample rounded up
            # t_sample can't be more than 2 hours
            self.recent_temps = np.full(
                (int(np.ceil(7200 / self.t_sample)), 4), -1.0)

            # acquire data from Lakeshore
            self.take_data = True
            while self.take_data:

                # get thermometry data
                temperatures_message = {
                    'timestamp': time.time(),
                    'block_name': 'temperatures',
                    'data': {}
                }

                temps = self.module.get_kelvin('0')  # array of four floats
                voltages = self.module.get_sensor('0')  # array of four floats
                for i, channel in enumerate(self.module.channels.values()):
                    channel_str = channel.input_name.replace(' ', '_')
                    temperatures_message['data'][channel_str + '_T'] = temps[i]
                    temperatures_message['data'][channel_str +
                                                 '_V'] = voltages[i]

                # append to recent temps array
                self.recent_temps = np.roll(self.recent_temps, 1, axis=0)
                self.recent_temps[0] = temps

                # publish to feed
                self.agent.publish_to_feed(
                    'temperatures', temperatures_message)

                # get heater data
                heaters_message = {
                    'timestamp': time.time(),
                    'block_name': 'heaters',
                    'data': {}
                }

                for i, heater in enumerate(self.module.heaters.values()):
                    heater_str = heater.output_name.replace(' ', '_')
                    heaters_message['data'][heater_str +
                                            '_Percent'] = heater.get_heater_percent()
                    heaters_message['data'][heater_str +
                                           '_Range'] = heater.get_heater_range()
                    heaters_message['data'][heater_str +
                                            '_Max_Current'] = heater.get_max_current()
                    heaters_message['data'][heater_str +
                                            '_Setpoint'] = heater.get_setpoint()

                # publish to feed
                self.agent.publish_to_feed('temperatures', heaters_message)

                # finish sample
                self.log.debug(
                    f'Sleeping for {np.round(self.t_sample)} seconds...')

                # release and reacquire lock between data acquisition
                self.lock.release()
                time.sleep(t_sample)
                if not self.lock.acquire(timeout=10, job='acq'):
                    print(
                        f"Lock could not be acquired because it is held by {self.lock.job}")
                    return False, 'Could not re-acquire lock'

        return True, 'Acquisition exited cleanly'

    def stop_acq(self, session, params=None):
        """Stops acq process."""
        if params is None:
            params = {}

        if self.take_data:
            self.take_data = False
            return True, 'Requested to stop taking data'
        else:
            return False, 'acq is not currently running'

    def set_heater_range(self, session, params):
        """Adjusts the heater range for servoing the load.

        Parameters
        ----------
        params : dict
            Contains parameters 'range' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_heater_range', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set range
            current_range = heater.get_heater_range()
            if params['range'] == current_range:
                print(
                    'Current heater range matches commanded value. Proceeding unchanged')
            else:
                heater.set_heater_range(params['range'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} range to {params['range']}")

        return True, f"Set {heater.output_name} range to {params['range']}"

    def set_pid(self, session, params):
        """Set the PID parameters for servoing the load.

        Parameters
        ----------
        params : dict
            Contains parameters 'P', 'I', 'D' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_pid', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set pid
            current_p, current_i, current_d = heater.get_pid()
            if params['P'] == current_p and params['I'] == current_i and params['D'] == current_d:
                print('Current heater PID matches commanded value. Proceeding unchanged')
            else:
                heater.set_pid(params['P'], params['I'], params['D'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} PID to {params['P']}, {params['I']}, {params['D']}")

        return True, f"Set {heater.output_name} PID to {params['P']}, {params['I']}, {params['D']}"

    def set_mode(self, session, params):
        """Sets the output mode of the heater.

        Parameters
        ----------
        params : dict
            Contains parameters 'mode' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_mode', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set mode
            current_mode = heater.get_mode()
            if params['mode'] == current_mode:
                print(
                    'Current heater mode matches commanded value. Proceeding unchanged')
            else:
                heater.set_mode(params['mode'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} mode to {params['mode']}")

        return True, f"Set {heater.output_name} mode to {params['mode']}"

    def set_heater_resistance(self, session, params):
        """Sets the heater resistance and resistance setting of the heater.

        Parameters
        ----------
        params : dict
            Contains parameters 'resistance' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_heater_resistance', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set heater resistance
            _ = heater.get_heater_resistance_setting()
            if params['resistance'] == heater.resistance:
                print(
                    'Current heater resistance matches commanded value. Proceeding unchanged')
            else:
                heater.set_heater_resistance(params['resistance'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} resistance to {params['resistance']}")

        return True, f"Set {heater.output_name} resistance to {params['resistance']}"

    def set_max_current(self, session, params):
        """Sets the heater resistance and resistance setting of the heater.

        Parameters
        ----------
        params : dict
            Contains parameters 'resistance' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_max_current', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set max current
            current_max_current = heater.get_max_current()
            if params['current'] == current_max_current:
                print(
                    'Current max current matches commanded value. Proceeding unchanged')
            else:
                heater.set_max_current(params['current'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} max current to {params['current']}")

        return True, f"Set {heater.output_name} max current to {params['current']}"

    def set_manual_out(self, session, params):
        """Sets the manual output of the heater.

        Parameters
        ----------
        params : dict
            Contains parameters 'percent' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_manual_out', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set manual out
            current_manual_out = heater.get_manual_out()
            if params['percent'] == current_manual_out:
                print('Current manual out matches commanded value. Proceeding unchanged')
            else:
                heater.set_manual_out(params['percent'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} manual out to {params['percent']}")

        return True, f"Set {heater.output_name} manual out to {params['percent']}"

    def set_input_channel(self, session, params):
        """Sets the input channel of the heater control loop.

        Parameters
        ----------
        params : dict
            Contains parameters 'input' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_input_channel', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set input channel
            current_input_channel = heater.get_input_channel()
            if params['input'] == current_input_channel:
                print(
                    'Current input channel matches commanded value. Proceeding unchanged')
            else:
                heater.set_input_channel(params['input'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {heater.output_name} input channel to {params['input']}")

        return True, f"Set {heater.output_name} input channel to {params['input']}"

    def set_setpoint(self, session, params):
        """Sets the setpoint of the heater control loop, after first turning ramp off.

        Parameters
        ----------
        params : dict
            Contains parameters 'setpoint' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_setpoint', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # set setpoint
            current_setpoint = heater.get_setpoint()
            if params['setpoint'] == current_setpoint:
                print('Current setpoint matches commanded value. Proceeding unchanged')
            else:
                heater.set_ramp_on_off('off')
                heater.set_setpoint(params['setpoint'])
                # static setpoint used in temp stability check to avoid ramping bug
                self.static_setpoint = params['setpoint']
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Turned ramp off and set {heater.output_name} setpoint to {params['setpoint']}")

        return True, f"Turned ramp off and set {heater.output_name} setpoint to {params['setpoint']}"

    def set_T_limit(self, session, params):
        """Sets the input T limit for use in control.

        Parameters
        ----------
        params : dict
            Contains parameters 'T_limit' (not optional), 'channel' (optional, default 'A'),
            and 'wait' (optional, default 1).
        """
        with self.lock.acquire_timeout(job='set_T_limit', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get channel
            channel_key = params.get('channel', 'A')  # default to input A
            channel = self.module.channels[channel_key]

            # set T limit
            current_limit = channel.get_T_limit()
            if params['T_limit'] == current_limit:
                print('Current T limit matches commanded value. Proceeding unchanged')
            else:
                channel.set_T_limit(params['T_limit'])
                time.sleep(params.get('wait', self.wait))

            session.add_message(
                f"Set {channel.input_name} T limit to {params['T_limit']}")

        return True, f"Set {channel.input_name} T limit to {params['T_limit']}"

    def servo_to_temperature(self, session, params):
        """A wrapper for setting the heater setpoint. Performs sanity checks on heater
        configuration before publishing setpoint:
            1. checks control mode of heater (closed loop)
            2. checks units of input channel (kelvin)
            3. resets setpoint to current temperature with ramp off
            4. sets ramp on to specified rate
            5. checks setpoint does not exceed input channel T_limit
            6. sets setpoint to commanded value

        Parameters
        ----------
        params : dict
            Contains parameters 'temperature' (not optional), 'ramp' (optional, default 0.1),
            'heater' (optional, default '2'), 'wait' (optional, default 1),
            'transport' (optional, default False), and 'transport_offset' (optional, default 0).

        Notes
        -----
        If param 'transport' is provided and True, the control loop restarts when the setpoint
        is first reached. This is useful for loads with long time cooling times or time constants
        to help minimize over/undershoot.

        If param 'transport' is provided and True, and 'transport_offset' is provided and positive,
        and the setpoint is higher than the current temperature, then the control loop will restart
        when the setpoint - transport_offset is first reached. This is useful to avoid  a "false positive"
        temperature stability check too shortly after transport completes.
        """
        # get sampling frequency
        t_sample = self.t_sample

        with self.lock.acquire_timeout(job='servo_to_temperature', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

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
                return False, f'{heater.output_name} does not have an input channel assigned'
            if self.module.channels[channel].get_units() != 'kelvin':
                session.add_message(
                    'Setting preferred units to kelvin on heater control input.')
                self.module.channels[channel].set_units('kelvin')

            # restart setpoint at current temperature
            current_temp = np.round(float(self.module.get_kelvin(channel)), 4)
            session.add_message(
                f'Turning ramp off and setting setpoint to current temperature {current_temp}')
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
                return False, f"{heater.output_name} control channel {channel} T limit of \
                     {T_limit}K is higher than setpoint of {params['temperature']}"

            # set setpoint
            if params['temperature'] == current_setpoint:
                print('Current setpoint matches commanded value. Proceeding unchanged')
            else:
                session.add_message(
                    f"Setting {heater.output_name} setpoint to {params['temperature']}")
                heater.set_setpoint(params['temperature'])
                # static setpoint used in temp stability check to avoid pulling the ramping setpoint
                self.static_setpoint = params['temperature']

                # if transport, restart control loop when setpoint first crossed
                if params.get('transport', False):

                    current_range = heater.get_heater_range()
                    starting_sign = np.sign(
                        params['temperature'] - current_temp)
                    transporting = True

                    # if we are raising temp, allow possibility of stopping transport at a cooler temp
                    T_offset = 0
                    if starting_sign > 0:
                        T_offset = params.get('transport_offset', 0)
                        if T_offset < 0:
                            return False, 'Transport offset temperature cannot be negative'

                    while transporting:
                        current_temp = np.round(
                            self.module.get_kelvin(channel), 4)
                        # check when this flips
                        current_sign = np.sign(
                            params['temperature'] - T_offset - current_temp)

                        # release and reacquire lock between data acquisition
                        self.lock.release()
                        time.sleep(t_sample)
                        if not self.lock.acquire(timeout=10, job='servo_to_temperature'):
                            print(
                                f"Lock could not be acquired because it is held by {self.lock.job}")
                            return False, 'Could not re-acquire lock'

                        if current_sign != starting_sign:
                            transporting = False  # update flag

                            # cycle control loop
                            session.add_message(
                                'Transport complete, restarting control loop at provided setpoint')
                            heater.set_heater_range('off')
                            # necessary 1s for prev command to register in ls336 firmware for some reason
                            time.sleep(1)
                            heater.set_heater_range(current_range)

                time.sleep(params.get('wait', self.wait))

        return True, f"Set {heater.output_name} setpoint to {params['temperature']}"

    def check_temperature_stability(self, session, params):
        """Assesses whether the load is stable around the setpoint to within some threshold.

        Parameters
        ----------
        params : dict
            Contains parameters 'threshold' (optiona, default 0.1), 'window' (option, default 900),
            'heater' (optional, default '2'), and 'wait' (optional, default 1).

        Notes
        -----
        Param 'threshold' sets the upper bound on the absolute temperature difference between
        the setpoint and any temperature from the input channel in the last 'window' seconds.

        Param 'window' sets the lookback time into the most recent temperature data, in seconds.
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

        with self.lock.acquire_timeout(job='check_temperature_stability', timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # get channel
            channel = heater.get_input_channel()
            channel_num = self.module.channels[channel].num

            # get current temp
            current_temp = np.round(self.module.get_kelvin(channel), 4)

            # check if recent temps and current temps are within threshold
            recent_temps = self.recent_temps[:num_idxs, channel_num-1]
            recent_temps = np.concatenate(
                (np.array([current_temp]), recent_temps))

            # get static setpoint if None
            if self.static_setpoint is None:
                self.static_setpoint = heater.get_setpoint()

            # avoids checking against the ramping setpoint, i.e. want to compare to commanded setpoint not mid-ramp setpoint
            setpoint = self.static_setpoint
            session.add_message(
                f'Maximum absolute difference in recent temps is {np.max(np.abs(recent_temps - setpoint))}K')

            if np.all(np.abs(recent_temps - setpoint) < threshold):
                session.add_message(
                    f'Recent temps are within {threshold}K of setpoint')
                return True, f'Servo temperature is stable within {threshold}K of setpoint'

            time.sleep(params.get('wait', self.wait))

        return False, f'Servo temperature is not stable within {threshold}K of setpoint'

    def get_channel_attribute(self, session, params):
        """Gets an arbitrary channel attribute and stores it in the session.data dict.
        Attribute must be the name of a method in the namespace of the Lakeshore336 Channel
        class, with a leading "get_" removed (see example).

        Parameters
        ----------
        params : dict
            Contains parameters 'attribute' (not optional), 'channel' (optional, default 'A'),
            and 'wait' (optional, default 1).

        Examples
        --------
        >>> ls.get_channel_attribute(attribute = 'T_limit').session['data']
        {'T_limit': 30.0}
        """
        with self.lock.acquire_timeout(job=f"get_{params['attribute']}", timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get channel
            channel_key = params.get('channel', 'A')  # default to input A
            channel = self.module.channels[channel_key]

            # check that attribute is a valid channel method
            if getattr(channel, f"get_{params['attribute']}", False) is not False:
                query = getattr(channel, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

            time.sleep(params.get('wait', self.wait))

        return True, f"Retrieved {channel.input_name} {params['attribute']}"

    def get_heater_attribute(self, session, params):
        """Gets an arbitrary heater attribute and stores in the session.data dict.
        Attribute must be the name of a method in the namespace of the Lakeshore336 Heater
        class, with a leading "get_" removed (see example).

        Parameters
        ----------
        params : dict
            Contains parameters 'attribute' (not optional), 'heater' (optional, default '2'),
            and 'wait' (optional, default 1).

        Examples
        --------
        >>> ls.get_heater_attribute(attribute = 'heater_range').session['data']
        {'heater_range': 'off'}
        """
        with self.lock.acquire_timeout(job=f"get_{params['attribute']}", timeout=3) as acquired:
            if not acquired:
                print(
                    f"Lock could not be acquired because it is held by {self.lock.job}")
                return False, 'Could not acquire lock'

            session.set_status('running')

            # get heater
            heater_key = params.get('heater', '2')  # default to 50W output
            heater = self.module.heaters[heater_key]

            # check that attribute is a valid heater method
            if getattr(heater, f"get_{params['attribute']}", False) is not False:
                query = getattr(heater, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

            time.sleep(params.get('wait', self.wait))

        return True, f"Retrieved {heater.output_name} {params['attribute']}"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the lakeshore")
    pgroup.add_argument('--f-sample', type=float, default=0.1,
                        help='The frequency of data acquisition')
    pgroup.add_argument('--wait', type=float, default=1.0,
                        help='The wait time after most operations')
    pgroup.add_argument('--threshold', type=float, default=0.1,
                        help='The upper bound on temperature differences for stability check')
    pgroup.add_argument('--window', type=float, default=600.,
                        help='The lookback time on temperature differences for stability check')
    pgroup.add_argument('--auto-acquire', type=bool, default=True,
                        help='Automatically start data acquisition on startup')
    return parser


if __name__ == '__main__':

    # Create an argument parser
    parser = make_parser()
    args = site_config.parse_args(
        agent_class='Lakeshore336Agent', parser=parser)

    # Automatically acquire data if requested
    init_params = False
    if args.auto_acquire:
        init_params = {'auto_acquire': True}

    print('I am in charge of device with serial number: %s' % args.serial_number)

    # Create a session and a runner which communicate over WAMP
    agent, runner = ocs_agent.init_site_agent(args)

    # Pass the new agent session to the agent class
    lake_agent = LS336_Agent(agent, args.serial_number, args.port, args.f_sample,
                             args.wait, args.threshold, args.window)

    # Register tasks (name, agent_function)
    agent.register_task(
        'init_lakeshore', lake_agent.init_lakeshore_task, startup=init_params)
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
    agent.register_process('acq', lake_agent.start_acq, lake_agent.stop_acq)

    # Run the agent
    runner.run(agent, auto_reconnect=True)
