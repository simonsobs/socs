import argparse
import os
import random
import threading
import time
from contextlib import contextmanager

import numpy as np
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.Lakeshore.Lakeshore370 import LS370


class YieldingLock:
    """A lock protected by a lock.  This braided arrangement guarantees
    that a thread waiting on the lock will get priority over a thread
    that has just released the lock and wants to reacquire it.

    The typical use case is a Process that wants to hold the lock as
    much as possible, but occasionally release the lock (without
    sleeping for long) so another thread can access a resource.  The
    method release_and_acquire() is provided to make this a one-liner.

    """

    def __init__(self, default_timeout=None):
        self.job = None
        self._next = threading.Lock()
        self._active = threading.Lock()
        self._default_timeout = default_timeout

    def acquire(self, timeout=None, job=None):
        if timeout is None:
            timeout = self._default_timeout
        if timeout is None or timeout == 0.:
            kw = {'blocking': False}
        else:
            kw = {'blocking': True, 'timeout': timeout}
        result = False
        if self._next.acquire(**kw):
            if self._active.acquire(**kw):
                self.job = job
                result = True
            self._next.release()
        return result

    def release(self):
        self.job = None
        return self._active.release()

    def release_and_acquire(self, timeout=None):
        job = self.job
        self.release()
        return self.acquire(timeout=timeout, job=job)

    @contextmanager
    def acquire_timeout(self, timeout=None, job='unnamed'):
        result = self.acquire(timeout=timeout, job=job)
        if result:
            try:
                yield result
            finally:
                self.release()
        else:
            yield result


class LS370_Agent:
    """Agent to connect to a single Lakeshore 370 device.

    Args:
        name (ApplicationSession): ApplicationSession for the Agent.
        port (str): Serial port for the 370 device, e.g. '/dev/ttyUSB2'
        fake_data (bool, optional): generates random numbers without connecting
            to LS if True.
        dwell_time_delay (int, optional): Amount of time, in seconds, to
            delay data collection after switching channels. Note this time
            should not include the change pause time, which is automatically
            accounted for. Will automatically be reduced to dwell_time - 1
            second if it is set longer than a channel's dwell time. This
            ensures at least one second of data collection at the end of a scan.

    """

    def __init__(self, agent, name, port, fake_data=False, dwell_time_delay=0):

        # self._acq_proc_lock is held for the duration of the acq Process.
        # Tasks that require acq to not be running, at all, should use
        # this lock.
        self._acq_proc_lock = TimeoutLock()

        # self._lock is held by the acq Process only when accessing
        # the hardware but released occasionally so that (short) Tasks
        # may run.  Use a YieldingLock to guarantee that a waiting
        # Task gets activated preferentially, even if the acq thread
        # immediately tries to reacquire.
        self._lock = YieldingLock(default_timeout=5)

        self.name = name
        self.port = port
        self.fake_data = fake_data
        self.dwell_time_delay = dwell_time_delay
        self.module = None
        self.thermometers = []

        self.log = agent.log
        self.initialized = False
        self.take_data = False

        self.agent = agent
        # Registers temperature feeds
        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    @ocs_agent.param('force', default=False, type=bool)
    def init_lakeshore(self, session, params=None):
        """init_lakeshore(auto_acquire=False, force=False)

        **Task** - Perform first time setup of the Lakeshore 370 communication.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
            force (bool, optional): Force re-initialize the lakeshore if True.

        """

        if self.initialized and not params['force']:
            self.log.info("Lakeshore already initialized. Returning...")
            return True, "Already initialized"

        with self._lock.acquire_timeout(job='init') as acquired1, \
                self._acq_proc_lock.acquire_timeout(timeout=0., job='init') \
                as acquired2:
            if not acquired1:
                self.log.warn(f"Could not start init because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"
            if not acquired2:
                self.log.warn(f"Could not start init because "
                              f"{self._acq_proc_lock.job} is already running")
                return False, "Could not acquire lock"

            if self.fake_data:
                self.res = random.randrange(1, 1000)
                session.add_message("No initialization since faking data")
                self.thermometers = ["thermA", "thermB"]
            else:
                self.module = LS370(self.port)
                print("Initialized Lakeshore module: {!s}".format(self.module))
                session.add_message("Lakeshore initilized with ID: %s" % self.module.id)

                self.thermometers = [channel.name for channel in self.module.channels]

            self.initialized = True

        # Start data acquisition if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Lakeshore module initialized.'

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()

        **Process** - Run data acquisition.

        """

        with self._acq_proc_lock.acquire_timeout(timeout=0, job='acq') \
                as acq_acquired, \
                self._lock.acquire_timeout(job='acq') as acquired:
            if not acq_acquired:
                self.log.warn(f"Could not start Process because "
                              f"{self._acq_proc_lock.job} is already running")
                return False, "Could not acquire lock"
            if not acquired:
                self.log.warn(f"Could not start Process because "
                              f"{self._lock.job} is holding the lock")
                return False, "Could not acquire lock"

            self.log.info("Starting data acquisition for {}".format(self.agent.agent_address))
            previous_channel = None
            last_release = time.time()

            self.take_data = True
            while self.take_data:

                # Relinquish sampling lock occasionally.
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self._lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self._lock.job}.")
                        continue

                if self.fake_data:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'fake-data',
                        'data': {}
                    }
                    for therm in self.thermometers:
                        reading = np.random.normal(self.res, 20)
                        data['data'][therm] = reading
                    time.sleep(.1)

                else:
                    active_channel = self.module.get_active_channel()

                    # The 370 reports the last updated measurement repeatedly
                    # during the "pause change time", this results in several
                    # stale datapoints being recorded. To get around this we
                    # query the pause time and skip data collection during it
                    # if the channel has changed (as it would if autoscan is
                    # enabled.)
                    if previous_channel != active_channel:
                        if previous_channel is not None:
                            pause_time = active_channel.get_pause()
                            self.log.debug("Pause time for {c}: {p}",
                                           c=active_channel.channel_num,
                                           p=pause_time)

                            dwell_time = active_channel.get_dwell()
                            self.log.debug("User set dwell_time_delay: {p}",
                                           p=self.dwell_time_delay)

                            # Check user set dwell time isn't too long
                            if self.dwell_time_delay > dwell_time:
                                self.log.warn("WARNING: User set dwell_time_delay of "
                                              + "{delay} s is larger than channel "
                                              + "dwell time of {chan_time} s. If "
                                              + "you are autoscanning this will "
                                              + "cause no data to be collected. "
                                              + "Reducing dwell time delay to {s} s.",
                                              delay=self.dwell_time_delay,
                                              chan_time=dwell_time,
                                              s=dwell_time - 1)
                                total_time = pause_time + dwell_time - 1
                            else:
                                total_time = pause_time + self.dwell_time_delay

                            for i in range(total_time):
                                self.log.debug("Sleeping for {t} more seconds...",
                                               t=total_time - i)
                                time.sleep(1)

                        # Track the last channel we measured
                        previous_channel = self.module.get_active_channel()

                    # Setup feed dictionary
                    channel_str = active_channel.name.replace(' ', '_')
                    data = {
                        'timestamp': time.time(),
                        'block_name': channel_str,
                        'data': {}
                    }

                    # Collect both temperature and resistance values from each Channel
                    data['data'][channel_str + '_T'] = \
                        self.module.get_temp(unit='kelvin', chan=active_channel.channel_num)
                    data['data'][channel_str + '_R'] = \
                        self.module.get_temp(unit='ohms', chan=active_channel.channel_num)

                    # Courtesy in case active channel has not changed
                    time.sleep(0.1)

                session.app.publish_to_feed('temperatures', data)

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('heater', type=str)
    @ocs_agent.param('range')
    @ocs_agent.param('wait', type=float, default=0)
    def set_heater_range(self, session, params):
        """set_heater_range(range, heater='sample', wait=0)

        **Task** - Adjust the heater range for servoing cryostat. Wait for a
        specified amount of time after the change.

        Parameters:
            heater (str): Name of heater to set range for, 'sample' by default
                (and the only implemented option.)
            range (str, float): see arguments in
                :func:`socs.Lakeshore.Lakeshore370.Heater.set_heater_range`
            wait (float, optional): Amount of time to wait after setting the
                heater range. This allows the servo time to adjust to the new range.

        """
        with self._lock.acquire_timeout(job='set_heater_range') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            heater_string = params.get('heater', 'sample')
            if heater_string.lower() == 'sample':
                heater = self.module.sample_heater
            elif heater_string.lower() == 'still':  # TODO: add still heater class to driver
                # heater = self.module.still_heater
                self.log.warn(f"{heater_string} heater not yet implemented in this agent, please modify client")

            current_range = heater.get_heater_range()

            if params['range'] == current_range:
                print("Current heater range matches commanded value. Proceeding unchanged.")
            else:
                heater.set_heater_range(params['range'])
                time.sleep(params['wait'])

        return True, f'Set {heater_string} heater range to {params["range"]}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    @ocs_agent.param('mode', type=str, choices=['current', 'voltage'])
    def set_excitation_mode(self, session, params):
        """set_excitation_mode(channel, mode)

        **Task** - Set the excitation mode of a specified channel.

        Parameters:
            channel (int): Channel to set the excitation mode for. Valid values
                are 1-16.
            mode (str): Excitation mode. Possible modes are 'current' or
                'voltage'.

        """
        with self._lock.acquire_timeout(job='set_excitation_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            self.module.chan_num2channel(params['channel']).set_excitation_mode(params['mode'])
            session.add_message(f'post message in agent for Set channel {params["channel"]} excitation mode to {params["mode"]}')
            print(f'print statement in agent for Set channel {params["channel"]} excitation mode to {params["mode"]}')

        return True, f'return text for Set channel {params["channel"]} excitation mode to {params["mode"]}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    @ocs_agent.param('value', type=float)
    def set_excitation(self, session, params):
        """set_excitation(channel, value)

        **Task** - Set the excitation voltage/current value of a specified
        channel.

        Parameters:
            channel (int): Channel to set the excitation for. Valid values
                are 1-16.
            value (float): Excitation value in volts or amps depending on set
                excitation mode. See
                :func:`socs.Lakeshore.Lakeshore370.Channel.set_excitation`

        """
        with self._lock.acquire_timeout(job='set_excitation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            current_excitation = self.module.chan_num2channel(params['channel']).get_excitation()

            if params['value'] == current_excitation:
                print(f'Channel {params["channel"]} excitation already set to {params["value"]}')
            else:
                self.module.chan_num2channel(params['channel']).set_excitation(params['value'])
                session.add_message(f'Set channel {params["channel"]} excitation to {params["value"]}')
                print(f'Set channel {params["channel"]} excitation to {params["value"]}')

        return True, f'Set channel {params["channel"]} excitation to {params["value"]}'

    @ocs_agent.param('P', type=int)
    @ocs_agent.param('I', type=int)
    @ocs_agent.param('D', type=int)
    def set_pid(self, session, params):
        """set_pid(P, I, D)

        **Task** - Set the PID parameters for servo control of fridge.

        Parameters:
            P (int): Proportional term for PID loop
            I (int): Integral term for the PID loop
            D (int): Derivative term for the PID loop

        Notes:
            Makes a call to :func:`socs.Lakeshore.Lakeshore370.Heater.set_pid`.

        """
        with self._lock.acquire_timeout(job='set_pid') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            self.module.sample_heater.set_pid(params["P"], params["I"], params["D"])
            session.add_message(f'post message text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')
            print(f'print text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')

        return True, f'return text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}'

    @ocs_agent.param('channel', type=int)
    def set_active_channel(self, session, params):
        """set_active_channel(channel)

        **Task** - Set the active channel on the LS370.

        Parameters:
            channel (int): Channel to switch readout to. Valid values are 1-16.

        """
        with self._lock.acquire_timeout(job='set_active_channel') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            self.module.set_active_channel(params["channel"])
            session.add_message(f'post message text for set channel to {params["channel"]}')
            print(f'print text for set channel to {params["channel"]}')

        return True, f'return text for set channel to {params["channel"]}'

    @ocs_agent.param('autoscan', type=bool)
    def set_autoscan(self, session, params):
        """set_autoscan(autoscan)

        **Task** - Sets autoscan on the LS370.

        Parameters:
            autoscan (bool): True to enable autoscan, False to disable.

        """
        with self._lock.acquire_timeout(job='set_autoscan') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            if params['autoscan']:
                self.module.enable_autoscan()
                self.log.info('enabled autoscan')
            else:
                self.module.disable_autoscan()
                self.log.info('disabled autoscan')

        return True, 'Set autoscan to {}'.format(params['autoscan'])

    @ocs_agent.param('temperature', type=float, check=lambda x: x < 1)
    @ocs_agent.param('channel', type=float, default=None)
    def servo_to_temperature(self, session, params):
        """servo_to_temperature(temperature, channel=None)

        **Task** - Servo to a given temperature using a closed loop PID on a
        fixed channel. This will automatically disable autoscan if enabled.

        Parameters:
            temperature (float): Temperature to servo to in units of Kelvin.
            channel (int, optional): Channel to servo off of.

        """
        with self._lock.acquire_timeout(job='servo_to_temperature') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            # Check we're in correct control mode for servo.
            if self.module.sample_heater.mode != 'Closed Loop':
                session.add_message('Changing control to Closed Loop mode for servo.')
                self.module.sample_heater.set_mode("Closed Loop")

            # Check we aren't autoscanning.
            if self.module.get_autoscan() is True:
                session.add_message('Autoscan is enabled, disabling for PID control on dedicated channel.')
                self.module.disable_autoscan()

            # Check to see if we passed an input channel, and if so change to it
            if params.get("channel", None) is not None:
                session.add_message(f'Changing heater input channel to {params.get("channel")}')
                self.module.sample_heater.set_input_channel(params.get("channel"))

            # Check we're scanning same channel expected by heater for control.
            if self.module.get_active_channel().channel_num != int(self.module.sample_heater.input):
                session.add_message('Changing active channel to expected heater control input')
                self.module.set_active_channel(int(self.module.sample_heater.input))

            # Check we're setup to take correct units.
            if self.module.sample_heater.units != 'kelvin':
                session.add_message('Setting preferred units to Kelvin on heater control.')
                self.module.sample_heater.set_units('kelvin')

            # Make sure we aren't servoing too high in temperature.
            if params["temperature"] > 1:
                return False, 'Servo temperature is set above 1K. Aborting.'

            self.module.sample_heater.set_setpoint(params["temperature"])

        return True, f'Setpoint now set to {params["temperature"]} K'

    @ocs_agent.param('measurements', type=int)
    @ocs_agent.param('threshold', type=float)
    def check_temperature_stability(self, session, params):
        """check_temperature_stability(measurements, threshold)

        Check servo temperature stability is within threshold.

        Parameters:
            measurements (int): number of measurements to average for stability
                check
            threshold (float): amount within which the average needs to be to
                the setpoint for stability

        """
        with self._lock.acquire_timeout(job='check_temp_stability') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            setpoint = float(self.module.sample_heater.get_setpoint())

            if params is None:
                params = {'measurements': 10, 'threshold': 0.5e-3}

            test_temps = []

            for i in range(params['measurements']):
                test_temps.append(self.module.get_temp())
                time.sleep(.1)  # sampling rate is 10 readings/sec, so wait 0.1 s for a new reading

            mean = np.mean(test_temps)
            session.add_message(f'Average of {params["measurements"]} measurements is {mean} K.')
            print(f'Average of {params["measurements"]} measurements is {mean} K.')

            if np.abs(mean - setpoint) < params['threshold']:
                print("passed threshold")
                session.add_message('Setpoint Difference: ' + str(mean - setpoint))
                session.add_message(f'Average is within {params["threshold"]} K threshold. Proceeding with calibration.')

                return True, f"Servo temperature is stable within {params['threshold']} K"

            else:
                print("we're in the else")
                # adjust_heater(t,rest)

        return False, f"Temperature not stable within {params['threshold']}."

    @ocs_agent.param('heater', type=str, choices=['sample', 'still'])
    @ocs_agent.param('mode', type=str, choices=['Off', 'Monitor Out', 'Open Loop', 'Zone', 'Still', 'Closed Loop', 'Warm up'])
    def set_output_mode(self, session, params=None):
        """set_output_mode(heater, mode)

        **Task** - Set output mode of the heater.

        Parameters:
            heater (str): Name of heater to set range for, either 'sample' or
                'still'.
            mode (str): Specifies mode of heater. Can be "Off", "Monitor Out",
                "Open Loop", "Zone", "Still", "Closed Loop", or "Warm up"

        """
        with self._lock.acquire_timeout(job='set_output_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            if params['heater'].lower() == 'still':
                # self.module.still_heater.set_mode(params['mode']) #TODO: add still heater to driver
                self.log.warn(f"{params['heater']} heater not yet implemented in this agent, please modify client")
            if params['heater'].lower() == 'sample':
                self.module.sample_heater.set_mode(params['mode'])
            self.log.info("Set {} output mode to {}".format(params['heater'], params['mode']))

        return True, "Set {} output mode to {}".format(params['heater'], params['mode'])

    @ocs_agent.param('heater', type=str, choices=['sample', 'still'])
    @ocs_agent.param('output', type=float)
    @ocs_agent.param('display', type=str, choices=['current', 'power'], default=None)
    def set_heater_output(self, session, params=None):
        """set_heater_output(heater, output, display=None)

        **Task** - Set display type and output of the heater.

        Parameters:
            heater (str): Name of heater to set range for, either 'sample' or
                'still'.
            output (float): Specifies heater output value. For possible values see
                :func:`socs.Lakeshore.Lakeshore370.Heater.set_heater_output`
            display (str, optional): Specifies heater display type. Can be
                "current" or "power". If None, heater display is not reset
                before setting output.

        """

        with self._lock.acquire_timeout(job='set_heater_output') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            heater = params['heater'].lower()
            output = params['output']

            display = params.get('display', None)

            if heater == 'still':  # TODO: add still heater to driver
                # self.module.still_heater.set_heater_output(output, display_type=display)
                self.log.warn(f"{heater} heater not yet implemented in this agent, please modify client")
            if heater.lower() == 'sample':
                self.log.info("display: {}\toutput: {}".format(display, output))
                self.module.sample_heater.set_heater_output(output, display_type=display)

            self.log.info("Set {} heater display to {}, output to {}".format(heater, display, output))

            data = {'timestamp': time.time(),
                    'block_name': '{}_heater_out'.format(heater),
                    'data': {'{}_heater_out'.format(heater): output}
                    }
            session.app.publish_to_feed('temperatures', data)

        return True, "Set {} display to {}, output to {}".format(heater, display, output)

    @ocs_agent.param('attribute', type=str)
    @ocs_agent.param('channel', type=int, default=1)
    def get_channel_attribute(self, session, params):
        """get_channel_attribute(attribute, channel=1)

        **Task** - Gets an arbitrary channel attribute, stored in the session.data dict.

        Parameters:
            attribute (str, optional): Attribute to get from the 370.
            channel (int, optional): Channel to get the attribute for.

        Notes:
            Channel attributes stored in the session.data object are in the
            structure::

                >>> response.session['data']
                {"calibration_curve": 21,
                 "dwell": 3,
                 "excitation": 6.32e-6,
                 "excitation_mode": "voltage",
                 "excitation_power": 2.0e-15,
                 "kelvin_reading": 100.0e-3,
                 "pause": 3,
                 "reading_status": ["T.UNDER"]
                 "resistance_range": 2.0e-3,
                 "resistance_reading": 10.0e3,
                 "temperature_coefficient": "negative",
                }

            Only attribute called with this method will be populated for the
            given channel. This example shows all available attributes.

        """
        with self._lock.acquire_timeout(job=f"get_{params['attribute']}", timeout=3) as acquired:
            if not acquired:
                print(f"Lock could not be acquired because it is held by {self._lock.job}")
                return False, 'Could not acquire lock'

            # get channel
            channel_key = int(params.get('channel', 1))
            channel = self.module.chan_num2channel(channel_key)

            # check that attribute is a valid channel method
            if getattr(channel, f"get_{params['attribute']}", False) is not False:
                query = getattr(channel, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

            time.sleep(.1)

        return True, f"Retrieved {channel.name} {params['attribute']}"

    @ocs_agent.param('attribute', type=str)
    def get_heater_attribute(self, session, params):
        """get_heater_attribute(attribute)

        **Task** - Gets an arbitrary heater attribute, stored in the session.data dict.

        Parameters:
            attribute (str): Heater attribute to get.

        Notes:
            Heater attributes stored in the session.data object are in the structure::

                >>> response.session['data']
                {"heater_range": 1e-3,
                 "heater_setup": ["current", 1e-3, 120],
                 "input_channel": 6,
                 "manual_out": 0.0,
                 "mode": "Closed Loop",
                 "pid": (80, 10, 0),
                 "setpoint": 100e-3,
                 "still_output", 10.607,
                 "units": "kelvin",
                }

            Only the attribute called with this method will be populated,
            this example just shows all available attributes.

        """
        with self._lock.acquire_timeout(job=f"get_{params['attribute']}", timeout=3) as acquired:
            if not acquired:
                print(f"Lock could not be acquired because it is held by {self._lock.job}")
                return False, 'Could not acquire lock'

            # get heater
            heater = self.module.sample_heater

            # check that attribute is a valid heater method
            if getattr(heater, f"get_{params['attribute']}", False) is not False:
                query = getattr(heater, f"get_{params['attribute']}")

            # get attribute
            resp = query()
            session.data[params['attribute']] = resp

            time.sleep(.1)

        return True, f"Retrieved sample heater {params['attribute']}"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=str, help='Full path to USB node for the lakeshore, e.g. "/dev/ttyUSB0"')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--mode')
    pgroup.add_argument('--fake-data', type=int, default=0,
                        help='Set non-zero to fake data, without hardware.')
    pgroup.add_argument('--dwell-time-delay', type=int, default=0,
                        help="Amount of time, in seconds, to delay data\
                              collection after switching channels. Note this\
                              time should not include the change pause time,\
                              which is automatically accounted for.\
                              Will automatically be reduced to dwell_time - 1\
                              second if it is set longer than a channel's dwell\
                              time. This ensures at least one second of data\
                              collection at the end of a scan.")
    pgroup.add_argument('--auto-acquire', type=bool, default=True,
                        help='Automatically start data acquisition on startup')

    return parser


def main(args=None):
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='Lakeshore370Agent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.auto_acquire:
        init_params = {'auto_acquire': True}

    LOG.info('I am in charge of device with serial number: %s' % args.serial_number)

    agent, runner = ocs_agent.init_site_agent(args)

    lake_agent = LS370_Agent(agent, args.serial_number, args.port,
                             fake_data=args.fake_data,
                             dwell_time_delay=args.dwell_time_delay)

    agent.register_task('init_lakeshore', lake_agent.init_lakeshore,
                        startup=init_params)
    agent.register_task('set_heater_range', lake_agent.set_heater_range)
    agent.register_task('set_excitation_mode', lake_agent.set_excitation_mode)
    agent.register_task('set_excitation', lake_agent.set_excitation)
    agent.register_task('set_pid', lake_agent.set_pid)
    agent.register_task('set_autoscan', lake_agent.set_autoscan)
    agent.register_task('set_active_channel', lake_agent.set_active_channel)
    agent.register_task('servo_to_temperature', lake_agent.servo_to_temperature)
    agent.register_task('check_temperature_stability', lake_agent.check_temperature_stability)
    agent.register_task('set_output_mode', lake_agent.set_output_mode)
    agent.register_task('set_heater_output', lake_agent.set_heater_output)
    agent.register_task('get_channel_attribute', lake_agent.get_channel_attribute)
    agent.register_task('get_heater_attribute', lake_agent.get_heater_attribute)
    agent.register_process('acq', lake_agent.acq, lake_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
