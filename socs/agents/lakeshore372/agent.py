import argparse
import os
import random
import threading
import time
from contextlib import contextmanager

import numpy as np
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from twisted.internet import reactor

from socs.Lakeshore.Lakeshore372 import LS372


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


class LS372_Agent:
    """Agent to connect to a single Lakeshore 372 device.

    Args:
        name (ApplicationSession): ApplicationSession for the Agent.
        ip (str): IP Address for the 372 device.
        fake_data (bool, optional): generates random numbers without connecting
            to LS if True.
        dwell_time_delay (int, optional): Amount of time, in seconds, to
            delay data collection after switching channels. Note this time
            should not include the change pause time, which is automatically
            accounted for. Will automatically be reduced to dwell_time - 1
            second if it is set longer than a channel's dwell time. This
            ensures at least one second of data collection at the end of a scan.
        enable_control_chan (bool, optional):
            If True, will read data from the control channel each iteration of
            the acq loop. Defaults to False.
    """

    def __init__(self, agent, name, ip, fake_data=False, dwell_time_delay=0,
                 enable_control_chan=False):

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
        self.ip = ip
        self.fake_data = fake_data
        self.dwell_time_delay = dwell_time_delay
        self.module = None
        self.thermometers = []

        self.log = agent.log
        self.initialized = False
        self.take_data = False
        self.control_chan_enabled = enable_control_chan

        self.agent = agent
        # Registers temperature feeds
        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('_')
    def enable_control_chan(self, session, params=None):
        """enable_control_chan()

        **Task** - Enables readout on the control channel (Channel A).

        """
        self.control_chan_enabled = True
        return True, 'Enabled control channel'

    @ocs_agent.param('_')
    def disable_control_chan(self, session, params=None):
        """disable_control_chan()

        **Task** - Disables readout on the control channel (Channel A).

        """
        self.control_chan_enabled = False
        return True, 'Disabled control channel'

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    @ocs_agent.param('acq_params', type=dict, default=None)
    @ocs_agent.param('force', default=False, type=bool)
    @ocs_agent.param('configfile', type=str, default=None)
    def init_lakeshore(self, session, params=None):
        """init_lakeshore(auto_acquire=False, acq_params=None, force=False, \
                          configfile=None)

        **Task** - Perform first time setup of the Lakeshore 372 communication.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
            acq_params (dict, optional): Params to pass to acq process if
                auto_acquire is True.
            force (bool, optional): Force initialization, even if already
                initialized. Defaults to False.
            configfile (str, optional): .yaml file for initializing 372 channel
                settings

        """
        if params is None:
            params = {}
        if self.initialized and not params.get('force', False):
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

            session.set_status('running')

            if self.fake_data:
                self.res = random.randrange(1, 1000)
                session.add_message("No initialization since faking data")
                self.thermometers = ["thermA", "thermB"]
            else:
                try:
                    self.module = LS372(self.ip)
                except ConnectionError:
                    self.log.error("Could not connect to the LS372. Exiting.")
                    reactor.callFromThread(reactor.stop)
                    return False, 'Lakeshore initialization failed'
                except Exception as e:
                    self.log.error(f"Unhandled exception encountered: {e}")
                    reactor.callFromThread(reactor.stop)
                    return False, 'Lakeshore initialization failed'

                print("Initialized Lakeshore module: {!s}".format(self.module))
                session.add_message("Lakeshore initilized with ID: %s" % self.module.id)

                self.thermometers = [channel.name for channel in self.module.channels]

            self.initialized = True

        if params.get('configfile') is not None:
            self.input_configfile(session, params)
            session.add_message("Lakeshore initial configurations uploaded using: %s" % params['configfile'])

        # Start data acquisition if requested
        if params.get('auto_acquire', False):
            self.agent.start('acq', params.get('acq_params', None))

        return True, 'Lakeshore module initialized.'

    @ocs_agent.param('sample_heater', default=False, type=bool)
    @ocs_agent.param('run_once', default=False, type=bool)
    def acq(self, session, params=None):
        """acq(sample_heater=False, run_once=False)

        **Process** - Acquire data from the Lakeshore 372.

        Parameters:
            sample_heater (bool, optional): Default is False. Will record
                values from the sample heater, typically used to servo a DR if
                True.

        Notes:
            The most recent data collected is stored in session data in the
            structure::

                >>> response.session['data']
                {"fields":
                    {"Channel_05": {"T": 293.644, "R": 33.752, "timestamp": 1601924482.722671},
                     "Channel_06": {"T": 0, "R": 1022.44, "timestamp": 1601924499.5258765},
                     "Channel_08": {"T": 0, "R": 1026.98, "timestamp": 1601924494.8172355},
                     "Channel_01": {"T": 293.41, "R": 108.093, "timestamp": 1601924450.9315426},
                     "Channel_02": {"T": 293.701, "R": 30.7398, "timestamp": 1601924466.6130798},
                     "control": {"T": 293.701, "R": 30.7398, "timestamp": 1601924466.6130798}
                    }
                }

        """
        pm = Pacemaker(10, quantize=True)

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

            session.set_status('running')
            self.log.info("Starting data acquisition for {}".format(self.agent.agent_address))
            previous_channel = None
            last_release = time.time()

            session.data = {"fields": {}}

            self.take_data = True
            while self.take_data:
                pm.sleep()

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

                    # The 372 reports the last updated measurement repeatedly
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

                    current_time = time.time()
                    data = {
                        'timestamp': current_time,
                        'block_name': active_channel.name,
                        'data': {}
                    }

                    # Collect both temperature and resistance values from each Channel
                    channel_str = active_channel.name.replace(' ', '_')
                    temp_reading = self.module.get_temp(unit='kelvin',
                                                        chan=active_channel.channel_num)
                    res_reading = self.module.get_temp(unit='ohms',
                                                       chan=active_channel.channel_num)

                    # For data feed
                    data['data'][channel_str + '_T'] = temp_reading
                    data['data'][channel_str + '_R'] = res_reading
                    session.app.publish_to_feed('temperatures', data)
                    self.log.debug("{data}", data=session.data)

                    # For session.data
                    field_dict = {channel_str: {"T": temp_reading,
                                                "R": res_reading,
                                                "timestamp": current_time}}
                    session.data['fields'].update(field_dict)

                    # Also queries control channel if enabled
                    if self.control_chan_enabled:
                        temp = self.module.get_temp(unit='kelvin', chan=0)
                        res = self.module.get_temp(unit='ohms', chan=0)
                        cur_time = time.time()
                        data = {
                            'timestamp': time.time(),
                            'block_name': 'control_chan',
                            'data': {
                                'control_T': temp,
                                'control_R': res
                            }
                        }
                        session.app.publish_to_feed('temperatures', data)
                        self.log.debug("{data}", data=session.data)
                        # Updates session data w/ control field
                        session.data['fields'].update({
                            'control': {
                                'T': temp, 'R': res, 'timestamp': cur_time
                            }
                        })

                if params.get("sample_heater", False):
                    # Sample Heater
                    heater = self.module.sample_heater
                    hout = heater.get_sample_heater_output()

                    current_time = time.time()
                    htr_data = {
                        'timestamp': current_time,
                        'block_name': "heaters",
                        'data': {}
                    }
                    htr_data['data']['sample_heater_output'] = hout

                    session.app.publish_to_feed('temperatures', htr_data)

                if params['run_once']:
                    break

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            session.set_status('stopping')
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('heater', type=str)
    @ocs_agent.param('range')
    @ocs_agent.param('wait', type=float, default=0)
    def set_heater_range(self, session, params):
        """set_heater_range(heater, range, wait=0)

        **Task** - Adjust the heater range for servoing cryostat. Wait for a
        specified amount of time after the change.

        Parameters:
            heater (str): Name of heater to set range for, either 'sample' or
                'still'.
            range (str, float): see arguments in
                :func:`socs.Lakeshore.Lakeshore372.Heater.set_heater_range`
            wait (float, optional): Amount of time to wait after setting the
                heater range. This allows the servo time to adjust to the new range.

        """
        with self._lock.acquire_timeout(job='set_heater_range') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            heater_string = params.get('heater', 'sample')
            if heater_string.lower() == 'sample':
                heater = self.module.sample_heater
            elif heater_string.lower() == 'still':
                heater = self.module.still_heater

            current_range = heater.get_heater_range()
            self.log.debug(f"Current heater range: {current_range}")

            if params['range'] == current_range:
                print("Current heater range matches commanded value. Proceeding unchanged.")
            else:
                heater.set_heater_range(params['range'])
                time.sleep(params.get('wait', 0))

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

            session.set_status('running')

            self.module.channels[params['channel']].set_excitation_mode(params['mode'])
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
                :func:`socs.Lakeshore.Lakeshore372.Channel.set_excitation`

        """
        with self._lock.acquire_timeout(job='set_excitation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_excitation = self.module.channels[params['channel']].get_excitation()
            mode = self.module.channels[params["channel"]].get_excitation_mode()
            units = 'amps' if mode == 'current' else 'volts'

            if params['value'] == current_excitation:
                session.add_message(f'Channel {params["channel"]} excitation {mode} already set to {params["value"]} {units}')
            else:
                self.module.channels[params['channel']].set_excitation(params['value'])
                session.add_message(f'Set channel {params["channel"]} excitation {mode} to {params["value"]} {units}')

        return True, f'Set channel {params["channel"]} excitation to {params["value"]} {units}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    def get_excitation(self, session, params):
        """get_excitation(channel)

        **Task** - Get the excitation voltage/current value of a specified
        channel.

        Parameters:
            channel (int): Channel to get the excitation for. Valid values
                are 1-16.
        """
        with self._lock.acquire_timeout(job='get_excitation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_excitation = self.module.channels[params["channel"]].get_excitation()
            mode = self.module.channels[params["channel"]].get_excitation_mode()
            units = 'amps' if mode == 'current' else 'volts'
            session.add_message(f'Channel {params["channel"]} excitation {mode} is {current_excitation} {units}')
            session.data = {"excitation": current_excitation}

        return True, f'Channel {params["channel"]} excitation {mode} is {current_excitation} {units}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    @ocs_agent.param('resistance_range', type=float)
    def set_resistance_range(self, session, params):
        """set_resistance_range(channel, resistance_range)

        **Task** - Set the resistance range for a specified channel.

        Parameters:
            channel (int): Channel to set the resistance range for. Valid values
                are 1-16.
            resistance_range (float): range in ohms we want to measure. Doesn't
                need to be exactly one of the options on the lakeshore, will select
                closest valid range, though note these are in increments of 2, 6.32,
                20, 63.2, etc.

        Notes:
            If autorange is on when you change the resistance range, it may try to change
            it to another value.
        """
        with self._lock.acquire_timeout(job='set_resistance_range') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_resistance_range = self.module.channels[params['channel']].get_resistance_range()

            if params['resistance_range'] == current_resistance_range:
                session.add_message(f'Channel {params["channel"]} resistance_range already set to {params["resistance_range"]}')
            else:
                self.module.channels[params['channel']].set_resistance_range(params['resistance_range'])
                session.add_message(f'Set channel {params["channel"]} resistance range to {params["resistance_range"]}')

        return True, f'Set channel {params["channel"]} resistance range to {params["resistance_range"]}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    def get_resistance_range(self, session, params):
        """get_resistance_range(channel)

        **Task** - Get the resistance range for a specified channel.

        Parameters:
            channel (int): Channel to get the resistance range for. Valid values
                are 1-16.
        """
        with self._lock.acquire_timeout(job='get_resistance_range') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_resistance_range = self.module.channels[params['channel']].get_resistance_range()
            session.add_message(f'Channel {params["channel"]} resistance range is {current_resistance_range}')
            session.data = {"resistance_range": current_resistance_range}

        return True, f'Channel {params["channel"]} resistance range is {current_resistance_range}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    @ocs_agent.param('dwell', type=int, check=lambda x: 1 <= x <= 200)
    def set_dwell(self, session, params):
        """set_dwell(channel, dwell)

        **Task** - Set the autoscanning dwell time for a particular channel.

        Parameters:
            channel (int): Channel to set the dwell time for. Valid values
                are 1-16.
            dwell (int): Dwell time in seconds, type is int and must be in the
                range 1-200 inclusive.
        """
        with self._lock.acquire_timeout(job='set_dwell') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.channels[params["channel"]].set_dwell(params["dwell"])
            session.add_message(f'Set dwell to {params["dwell"]}')

        return True, f'Set channel {params["channel"]} dwell time to {params["dwell"]}'

    @ocs_agent.param('channel', type=int, check=lambda x: 1 <= x <= 16)
    def get_dwell(self, session, params):
        """get_dwell(channel)

        **Task** - Get the autoscanning dwell time for a particular channel.

        Parameters:
            channel (int): Channel to get the dwell time for. Valid values
                are 1-16.
        """
        with self._lock.acquire_timeout(job='set_dwell') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_dwell = self.module.channels[params["channel"]].get_dwell()
            session.add_message(f'Dwell time for channel {params["channel"]} is {current_dwell}')
            session.data = {"dwell_time": current_dwell}

        return True, f'Channel {params["channel"]} dwell time is {current_dwell}'

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
            Makes a call to :func:`socs.Lakeshore.Lakeshore372.Heater.set_pid`.

        """
        with self._lock.acquire_timeout(job='set_pid') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.sample_heater.set_pid(params["P"], params["I"], params["D"])
            session.add_message(f'post message text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')
            print(f'print text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')

        return True, f'return text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}'

    @ocs_agent.param('channel', type=int)
    def set_active_channel(self, session, params):
        """set_active_channel(channel)

        **Task** - Set the active channel on the LS372.

        Parameters:
            channel (int): Channel to switch readout to. Valid values are 1-16.

        """
        with self._lock.acquire_timeout(job='set_active_channel') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.set_active_channel(params["channel"])
            session.add_message(f'post message text for set channel to {params["channel"]}')
            print(f'print text for set channel to {params["channel"]}')

        return True, f'return text for set channel to {params["channel"]}'

    @ocs_agent.param('autoscan', type=bool)
    def set_autoscan(self, session, params):
        """set_autoscan(autoscan)

        **Task** - Sets autoscan on the LS372.

        Parameters:
            autoscan (bool): True to enable autoscan, False to disable.

        """
        with self._lock.acquire_timeout(job='set_autoscan') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            if params['autoscan']:
                self.module.enable_autoscan()
                self.log.info('enabled autoscan')
            else:
                self.module.disable_autoscan()
                self.log.info('disabled autoscan')

        return True, 'Set autoscan to {}'.format(params['autoscan'])

    @ocs_agent.param('temperature', type=float, check=lambda x: x < 1)
    def servo_to_temperature(self, session, params):
        """servo_to_temperature(temperature)

        **Task** - Servo to a given temperature using a closed loop PID on a
        fixed channel. This will automatically disable autoscan if enabled.

        Parameters:
            temperature (float): Temperature to servo to in units of Kelvin.

        """
        with self._lock.acquire_timeout(job='servo_to_temperature') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            # Check we're in correct control mode for servo.
            if self.module.sample_heater.mode != 'Closed Loop':
                session.add_message('Changing control to Closed Loop mode for servo.')
                self.module.sample_heater.set_mode("Closed Loop")

            # Check we aren't autoscanning.
            if self.module.get_autoscan() is True:
                session.add_message('Autoscan is enabled, disabling for PID control on dedicated channel.')
                self.module.disable_autoscan()

            # Check we're scanning same channel expected by heater for control.
            if self.module.get_active_channel().channel_num != int(self.module.sample_heater.input):
                session.add_message('Changing active channel to expected heater control input')
                self.module.set_active_channel(int(self.module.sample_heater.input))

            # Check we're setup to take correct units.
            if self.module.get_active_channel().units != 'kelvin':
                session.add_message('Setting preferred units to Kelvin on heater control input.')
                self.module.get_active_channel().set_units('kelvin')

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

            session.set_status('running')

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

            session.set_status('running')

            if params['heater'].lower() == 'still':
                self.module.still_heater.set_mode(params['mode'])
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
                :func:`socs.Lakeshore.Lakeshore372.Heater.set_heater_output`
            display (str, optional): Specifies heater display type. Can be
                "current" or "power". If None, heater display is not reset
                before setting output.

        Notes:
            For the still heater this sets the still heater manual output, *not*
            the still heater still output. Use
            :func:`LS372_Agent.set_still_output()`
            instead to set the still output.

        """
        with self._lock.acquire_timeout(job='set_heater_output') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            heater = params['heater'].lower()
            output = params['output']

            display = params.get('display', None)

            if heater == 'still':
                self.module.still_heater.set_heater_output(output, display_type=display)
            if heater.lower() == 'sample':
                self.log.info("display: {}\toutput: {}".format(display, output))
                self.module.sample_heater.set_heater_output(output, display_type=display)

            self.log.info("Set {} heater display to {}, output to {}".format(heater, display, output))

            session.set_status('running')

            data = {'timestamp': time.time(),
                    'block_name': '{}_heater_out'.format(heater),
                    'data': {'{}_heater_out'.format(heater): output}
                    }
            session.app.publish_to_feed('temperatures', data)

        return True, "Set {} display to {}, output to {}".format(heater, display, output)

    @ocs_agent.param('output', type=float, check=lambda x: 0 <= x <= 100)
    def set_still_output(self, session, params=None):
        """set_still_output(output)

        **Task** - Set the still output on the still heater. This is different
        than the manual output on the still heater. Use
        :func:`LS372_Agent.set_heater_output()` for that.

        Parameters:
            output (float): Specifies still heater output value as a percentage. Can be any
                number between 0 and 100.

        """
        with self._lock.acquire_timeout(job='set_still_output') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            output = params['output']

            self.module.still_heater.set_still_output(output)

            self.log.info("Set still output to {}".format(output))

            session.set_status('running')

            data = {'timestamp': time.time(),
                    'block_name': 'still_heater_still_out',
                    'data': {'still_heater_still_out': output}
                    }
            session.app.publish_to_feed('temperatures', data)

        return True, "Set still output to {}".format(output)

    @ocs_agent.param('_')
    def get_still_output(self, session, params=None):
        """get_still_output()

        **Task** - Gets the current still output on the still heater.

        Notes:
            The still heater output is stored in the session data
            object in the format::

              >>> response.session['data']
              {"still_heater_still_out": 9.628}

        """
        with self._lock.acquire_timeout(job='get_still_output') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            still_output = self.module.still_heater.get_still_output()

            self.log.info("Current still output is {}".format(still_output))

            session.set_status('running')
            session.data = {"still_heater_still_out": still_output}

        return True, "Current still output is {}".format(still_output)

    @ocs_agent.param('configfile', type=str)
    def input_configfile(self, session, params=None):
        """input_configfile(configfile)

        **Task** - Upload 372 configuration file to initialize channel/device
        settings.

        Parameters:
            configfile (str): name of .yaml config file

        """
        with self._lock.acquire_timeout(job='input_configfile') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            # path to configfile in docker container
            configpath = os.environ.get("OCS_CONFIG_DIR", "/config/")
            configfile = params['configfile']

            ls372configs = os.path.join(configpath, configfile)
            with open(ls372configs) as f:
                config = yaml.safe_load(f)

            ls = self.module
            ls_serial = ls.id.split(',')[2]

            device_config = config[ls_serial]['device_settings']
            ls_chann_settings = config[ls_serial]['channel']

            session.set_status('running')

            # enable/disable autoscan
            if device_config['autoscan'] == 'on':
                ls.enable_autoscan()
                self.log.info("autoscan enabled")
            elif device_config['autoscan'] == 'off':
                ls.disable_autoscan()
                self.log.info("autoscan disabled")

            for i in ls_chann_settings:
                # enable/disable channel
                if ls_chann_settings[i]['enable'] == 'on':
                    ls.channels[i].enable_channel()
                    self.log.info("CH.{channel} enabled".format(channel=i))
                elif ls_chann_settings[i]['enable'] == 'off':
                    ls.channels[i].disable_channel()
                    self.log.info("CH.{channel} disabled".format(channel=i))

                # autorange
                if ls_chann_settings[i]['autorange'] == 'on':
                    ls.channels[i].enable_autorange()
                    self.log.info("autorange on")
                elif ls_chann_settings[i]['autorange'] == 'off':
                    ls.channels[i].disable_autorange()
                    self.log.info("autorange off")

                excitation_mode = ls_chann_settings[i]['excitation_mode']
                ls.channels[i].set_excitation_mode(excitation_mode)
                self.log.info("excitation mode for CH.{channel} set to {exc_mode}".format(channel=i, exc_mode=excitation_mode))

                excitation_value = ls_chann_settings[i]['excitation_value']
                ls.channels[i].set_excitation(excitation_value)
                self.log.info("excitation for CH.{channel} set to {exc}".format(channel=i, exc=excitation_value))

                dwell = ls_chann_settings[i]['dwell']
                ls.channels[i].set_dwell(dwell)
                self.log.info("dwell for CH.{channel} is set to {dwell}".format(channel=i, dwell=dwell))

                pause = ls_chann_settings[i]['pause']
                ls.channels[i].set_pause(pause)
                self.log.info("pause for CH.{channel} is set to {pause}".format(channel=i, pause=pause))

                calibration_curvenum = ls_chann_settings[i]['calibration_curve_num']
                ls.channels[i].set_calibration_curve(calibration_curvenum)
                self.log.info("calibration curve for CH.{channel} set to {cal_curve}".format(channel=i, cal_curve=calibration_curvenum))
                tempco = ls_chann_settings[i]['temperature_coeff']
                ls.channels[i].set_temperature_coefficient(tempco)
                self.log.info("temperature coeff. for CH.{channel} set to {tempco}".format(channel=i, tempco=tempco))

        return True, "Uploaded {}".format(configfile)


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--serial-number')
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
    pgroup.add_argument('--mode', type=str, default='acq',
                        choices=['idle', 'init', 'acq'],
                        help="Starting action for the Agent.")
    pgroup.add_argument('--sample-heater', type=bool, default=False,
                        help='Record sample heater output during acquisition.')
    pgroup.add_argument('--enable-control-chan', action='store_true',
                        help='Enable reading of the control input each acq cycle')
    pgroup.add_argument('--configfile', type=str, help='Yaml file for initializing 372 settings')

    return parser


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='Lakeshore372Agent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False,
                       'acq_params': {'sample_heater': args.sample_heater},
                       'configfile': args.configfile}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True,
                       'acq_params': {'sample_heater': args.sample_heater}}

    # Interpret options in the context of site_config.
    print('I am in charge of device with serial number: %s' % args.serial_number)

    agent, runner = ocs_agent.init_site_agent(args)

    lake_agent = LS372_Agent(agent, args.serial_number, args.ip_address,
                             fake_data=args.fake_data,
                             dwell_time_delay=args.dwell_time_delay,
                             enable_control_chan=args.enable_control_chan)

    agent.register_task('init_lakeshore', lake_agent.init_lakeshore,
                        startup=init_params)
    agent.register_task('set_heater_range', lake_agent.set_heater_range)
    agent.register_task('set_excitation_mode', lake_agent.set_excitation_mode)
    agent.register_task('set_excitation', lake_agent.set_excitation)
    agent.register_task('get_excitation', lake_agent.get_excitation)
    agent.register_task('set_resistance_range', lake_agent.set_resistance_range)
    agent.register_task('get_resistance_range', lake_agent.get_resistance_range)
    agent.register_task('set_dwell', lake_agent.set_dwell)
    agent.register_task('get_dwell', lake_agent.get_dwell)
    agent.register_task('set_pid', lake_agent.set_pid)
    agent.register_task('set_autoscan', lake_agent.set_autoscan)
    agent.register_task('set_active_channel', lake_agent.set_active_channel)
    agent.register_task('servo_to_temperature', lake_agent.servo_to_temperature)
    agent.register_task('check_temperature_stability', lake_agent.check_temperature_stability)
    agent.register_task('set_output_mode', lake_agent.set_output_mode)
    agent.register_task('set_heater_output', lake_agent.set_heater_output)
    agent.register_task('set_still_output', lake_agent.set_still_output)
    agent.register_task('get_still_output', lake_agent.get_still_output)
    agent.register_process('acq', lake_agent.acq, lake_agent._stop_acq)
    agent.register_task('enable_control_chan', lake_agent.enable_control_chan)
    agent.register_task('disable_control_chan', lake_agent.disable_control_chan)
    agent.register_task('input_configfile', lake_agent.input_configfile)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
