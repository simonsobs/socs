import argparse
import os
import socket
import time
from typing import Optional

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.scpi_psu.drivers import PsuInterface, ScpiPsuInterface

# For logging
txaio.use_twisted()


class ScpiPsuAgent:
    def __init__(self, agent, ip_address, gpib_slot=None, port=None):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.gpib_slot = None
        self.port = None
        self.monitor = False

        self.psu: Optional[ScpiPsuAgent] = None

        if gpib_slot is not None:
            self.gpib_slot = int(gpib_slot)
        if port is not None:
            self.port = int(port)

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 10 * 60,
        }
        self.agent.register_feed('psu_output',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init()

        **Task** - Initialize connection to the power supply.

        """
        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            if self.gpib_slot is None and self.port is None:
                self.log.error('Either --gpib-slot or --port must be specified')
                return False, "Parameter not set"
            elif self.port is None:  # Use the old Prologix-based GPIB code
                try:
                    self.psu = PsuInterface(self.ip_address, self.gpib_slot)
                    self.idn = self.psu.identify()
                except socket.timeout as e:
                    self.log.error(f"PSU timed out during connect: {e}")
                    return False, "Timeout"
            else:  # Use the new direct ethernet connection code
                try:
                    self.psu = ScpiPsuInterface(self.ip_address, port=self.port)
                    self.idn = self.psu.identify()
                except socket.timeout as e:
                    self.log.error(f"PSU timed out during connect: {e}")
                    return False, "Timeout"
                except ValueError as e:
                    if (e.args[0].startswith('Model number')):
                        self.log.warn(f"PSU initialization: {e}. \
                                Number of channels defaults to 3. \
                                Suggest appending {e.args[-1]} to the list \
                                of known model numbers in scpi_psu/drivers.py")
                    else:
                        self.log.error(f"PSU initialization resulted in unknown ValueError: {e}")
                        return False, "ValueError"

            self.log.info("Connected to psu: {}".format(self.idn))

        auto_acquire = params.get('auto_acquire', False)

        if auto_acquire:
            acq_params = None
            if self.psu.num_channels != 0:
                acq_params = {'channels': [i + 1 for i in range(self.psu.num_channels)]}
            self.agent.start('monitor_output', acq_params)
        return True, 'Initialized PSU.'

    def _initialize_module(self):
        """Initialize the ScpiPsu module."""
        try:
            if self.port is None:
                self.psu = PsuInterface(self.ip_address, self.gpib_slot)
            else:
                self.psu = ScpiPsuInterface(self.ip_address, port=self.port)
        except (socket.timeout, OSError) as e:
            self.log.warn(f"Error establishing connection: {e}")
            self.psu = None
            return False

        self.idn = self.psu.identify()
        self.log.info("Connected to psu: {}".format(self.idn))
        self.log.info("Clearing event registers and error queue")
        self.psu.clear()
        return True

    @ocs_agent.param('wait', type=float, default=1)
    @ocs_agent.param('channels', type=list, default=[1, 2, 3])
    @ocs_agent.param('test_mode', type=bool, default=False)
    def monitor_output(self, session, params=None):
        """monitor_output(wait=1, channels=[1, 2, 3], test_mode=False)

        **Process** - Continuously monitor PSU output current and voltage.

        Parameters:
            wait (float, optional): Time to wait between measurements
                [seconds].
            channels (list[int], optional): Channels to monitor. [1, 2, 3] by
                default.
            test_mode (bool, optional): Exit process after single loop if True.
                Defaults to False.

        """
        self.monitor = True

        while self.monitor:
            time.sleep(params['wait'])
            with self.lock.acquire_timeout(1) as acquired:
                if not acquired:
                    self.log.warn("Could not acquire in monitor_current")
                    continue

                if not self.psu:
                    self._initialize_module()
                    continue

                data = {
                    'timestamp': time.time(),
                    'block_name': 'output',
                    'data': {}
                }

                try:
                    for chan in params['channels']:
                        if self.psu.get_output(chan):
                            data['data']["Voltage_{}".format(chan)] = self.psu.get_volt(chan)
                            data['data']["Current_{}".format(chan)] = self.psu.get_curr(chan)
                        else:
                            self.log.warn("Cannot measure output when output is disabled")
                            self.monitor = False
                            return False, "Cannot measure output when output is disabled"
                except socket.timeout as e:
                    self.log.warn(f"TimeoutError: {e}")
                    self.log.info("Attempting to reconnect")
                    self.psu = None
                    continue

                self.agent.publish_to_feed('psu_output', data)

                # Allow this process to be queried to return current data
                session.data = data

            if params['test_mode']:
                break

        return True, "Finished monitoring current"

    def stop_monitoring(self, session, params=None):
        self.monitor = False
        return True, "Stopping current monitor"

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    def get_voltage(self, session, params=None):
        """get_voltage(channel)

        **Task** - Measure and return the voltage of the power supply.

        Parameters:
            channel (int): Channel number (1, 2, or 3).

        Examples:
            Example for calling in a client::

                client.get_voltage(channel=1)

        Notes:
            An example of the session data::

                >>> response.session['data']
                {'timestamp': 1723671503.4899583,
                 'channel': 1,
                 'voltage': 0.0512836}

        """
        chan = params['channel']
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                if self.psu.get_output(chan):
                    data = {
                        'timestamp': time.time(),
                        'channel': chan,
                        'voltage': self.psu.get_volt(chan)
                    }

                    session.data = data
                else:
                    return False, "Cannot measure output when output is disabled."
            else:
                return False, "Could not acquire lock"
        return True, 'Channel {} voltage measured'.format(chan)

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    @ocs_agent.param('volts', type=float, check=lambda x: 0 <= x <= 30)
    def set_voltage(self, session, params=None):
        """set_voltage(channel, volts)

        **Task** - Set the voltage of the power supply.

        Parameters:
            channel (int): Channel number (1, 2, or 3).
            volts (float): Voltage to set. Must be between 0 and 30.

        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_volt(params['channel'], params['volts'])
            else:
                return False, "Could not acquire lock"

        return True, 'Set channel {} voltage to {}'.format(params['channel'], params['volts'])

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    def get_current(self, session, params=None):
        """get_current(channel)

        **Task** - Measure and return the current of the power supply.

        Parameters:
            channel (int): Channel number (1, 2, or 3).

        Examples:
            Example for calling in a client::

                client.get_current(channel=1)

        Notes:
            An example of the session data::

                >>> response.session['data']
                {'timestamp': 1723671503.4899583,
                 'channel' : 1,
                 'current': 0.0103236}

        """
        chan = params['channel']
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                # Check if output is enabled before measuring
                if self.psu.get_output(chan):
                    data = {
                        'timestamp': time.time(),
                        'channel': chan,
                        'current': self.psu.get_curr(chan)
                    }
                    session.data = data
                else:
                    return False, "Cannot measure output when output is disabled."
            else:
                return False, "Could not acquire lock"
        return True, 'Channel {} current measured'.format(chan)

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    @ocs_agent.param('current', type=float)
    def set_current(self, session, params=None):
        """set_current(channel, current)

        **Task** - Set the current of the power supply.

        Parameters:
            channel (int): Channel number (1, 2, or 3).
            current (float): Current to set.

        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_curr(params['channel'], params['current'])
            else:
                return False, "Could not acquire lock"

        return True, 'Set channel {} current to {}'.format(params['channel'], params['current'])

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    def get_output(self, session, params=None):
        """get_output(channel)

        **Task** - Check if channel ouput is enabled or disabled.

        Parameters:
            channel (int): Channel number (1, 2, or 3).

        Examples:
            Example for calling in a client::

                client.get_output(channel=1)

        Notes:
            An example of the session data::

                >>> response.session['data']
                {'timestamp': 1723671503.4899583,
                 'channel': 1,
                 'state': 1}

        """
        chan = params['channel']
        enabled = False
        data = {}
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                data = {
                    'timestamp': time.time(),
                    'channel': chan,
                    'state': self.psu.get_output(chan)
                }
                session.data = data
                enabled = bool(data['state'])
            else:
                return False, "Could not acquire lock."
        if enabled:
            return True, 'Channel {} output is currently enabled.'.format(chan)
        else:
            return True, 'Channel {} output is currently disabled.'.format(chan)

    @ocs_agent.param('channel', type=int, choices=[1, 2, 3])
    @ocs_agent.param('state', type=bool)
    def set_output(self, session, params=None):
        """set_output(channel, state)

        **Task** - Turn a channel on or off.

        Parameters:
            channel (int): Channel number (1, 2, or 3).
            state (bool): True for on, False for off.

        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_output(params['channel'], params['state'])
            else:
                return False, "Could not acquire lock"

        return True, 'Initialized PSU.'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--gpib-slot')
    pgroup.add_argument('--port')
    pgroup.add_argument('--mode', type=str, default='acq',
                        choices=['init', 'acq'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='ScpiPsuAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}
    agent, runner = ocs_agent.init_site_agent(args)

    p = ScpiPsuAgent(agent, args.ip_address, args.gpib_slot, port=args.port)

    agent.register_task('init', p.init, startup=init_params)
    agent.register_task('set_voltage', p.set_voltage)
    agent.register_task('set_current', p.set_current)
    agent.register_task('set_output', p.set_output)

    agent.register_task('get_voltage', p.get_voltage)
    agent.register_task('get_current', p.get_current)
    agent.register_task('get_output', p.get_output)

    agent.register_process('monitor_output', p.monitor_output, p.stop_monitoring)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
