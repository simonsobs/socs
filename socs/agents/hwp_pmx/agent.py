import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet import reactor

import socs.agents.hwp_pmx.drivers.PMX_ethernet as pmx

txaio.use_twisted()


class HWPPMXAgent:
    """Agent for interfacing with a PMX Kikusui power supply
    to control the current and voltage that drive the rotation of the CHWP.

    Args:
        ip (str): IP address for the PMX Kikusui power supply
        port (str): Port for the PMX Kikusui power supply
        f_sample (float): sampling frequency (Hz)
    """

    def __init__(self, agent, ip, port, f_sample=1):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port

        self.f_sample = f_sample

        self._initialized = False
        self.take_data = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppmx', record=True, agg_params=agg_params, buffer_time=1)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_connection(self, session, params=None):
        """init_connection(auto_acquire=False)
        **Task** - Initialize connection to PMX

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
        """
        if self._initialized:
            self.log.info("Connection already initialized. Returning...")
            return True, "Connection already initialized"

        with self.lock.acquire_timeout(0, job='init_connection') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run init_connection because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            try:
                self.dev = pmx.PMX(ip=self.ip, port=self.port)
                self.log.info('Connected to PMX Kikusui')
            except BrokenPipeError:
                self.log.error('Could not establish connection to PMX Kikusui')
                reactor.callFromThread(reactor.stop)
                return False, 'Unable to connect to PMX Kikusui'

        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Connection to PMX established'

    def set_on(self, session, params):
        """set_on()
        **Task** - Turn on the PMX Kikusui.
        """
        with self.lock.acquire_timeout(3, job='set_on') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.turn_on()
        return True, 'Set PMX Kikusui on'

    def set_off(self, session, params):
        """set_off()
        **Task** - Turn off the PMX Kikusui.
        """
        with self.lock.acquire_timeout(3, job='set_off') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.turn_off()
        return True, 'Set PMX Kikusui off'

    @ocs_agent.param('curr', default=0, type=float, check=lambda x: 0 <= x <= 3)
    def set_i(self, session, params):
        """set_i(curr=0)
        **Task** - Set the current.

        Parameters:
            curr (float): set current
        """
        with self.lock.acquire_timeout(3, job='set_i') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set i because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            msg, val = self.dev.set_current(params['curr'])
        return True, msg

    @ocs_agent.param('volt', default=0, type=float, check=lambda x: 0 <= x <= 35)
    def set_v(self, session, params):
        """set_v(volt=0)
        **Task** - Set the voltage.

        Parameters:
            volt (float): set voltage
        """
        with self.lock.acquire_timeout(3, job='set_v') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set v because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            msg, val = self.dev.set_voltage(params['volt'])
        return True, msg

    @ocs_agent.param('curr', default=1., type=float, check=lambda x: 0. <= x <= 3.)
    def set_i_lim(self, session, params):
        """set_i_lim(curr=1)
        **Task** - Set the drive current limit.

        Parameters:
            curr (float): limit current
        """
        with self.lock.acquire_timeout(3, job='set_i_lim') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set v lim because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            msg = self.dev.set_current_limit(params['curr'])
        return True, msg

    @ocs_agent.param('volt', default=32., type=float, check=lambda x: 0. <= x <= 35.)
    def set_v_lim(self, session, params):
        """set_v_lim(volt=32)
        **Task** - Set the drive voltage limit.

        Parameters:
            volt (float): limit voltage
        """
        with self.lock.acquire_timeout(3, job='set_v_lim') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set v lim because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            msg = self.dev.set_voltage_limit(params['volt'])
        return True, msg

    def use_ext(self, session, params):
        """use_ext()
        **Task** - Set the PMX Kikusui to use an external voltage control. Doing so
        enables PID control.
        """
        with self.lock.acquire_timeout(3, job='use_ext') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not use external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.use_external_voltage()
        return True, 'Set PMX Kikusui to PID control'

    def ign_ext(self, session, params):
        """ign_ext()
        **Task** - Set the PMX Kiksui to ignore external voltage control. Doing so
        disables the PID and switches to direct control.
        """
        with self.lock.acquire_timeout(3, job='ign_ext') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not ignore external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.ign_external_voltage()
        return True, 'Set PMX Kikusui to direct control'

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq(test_mode=False)

        **Process** - Start data acquisition.

        Parameters:
            test_mode (bool, optional): Run the Process loop only once.
                This is meant only for testing. Default is False.

        Notes:
            The most recent data collected is stored in session data in the
            structure::

                >>> response.session['data']
                {'curr': 0,
                 'volt': 0,
                 'last_updated': 1649085992.719602}

        """
        sleep_time = 1 / self.f_sample - 0.01

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')
            self.take_data = True

            last_release = time.time()
            while self.take_data:
                current_time = time.time()
                if current_time - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire lock, currently held by {self.lock.job}.")
                        continue

                data = {
                    'timestamp': current_time,
                    'block_name': 'hwppmx',
                    'data': {}
                }
                msg, curr = self.dev.meas_current()
                data['data']['current'] = curr
                msg, volt = self.dev.meas_voltage()
                data['data']['voltage'] = volt

                self.agent.publish_to_feed('hwppmx', data)
                session.data = {'curr': curr,
                                'volt': volt,
                                'last_updated': current_time}

                time.sleep(sleep_time)

                if params['test_mode']:
                    break

            self.agent.feeds['hwppmx'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stop acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip', type=str,
                        help="ip address for kikusui PMX")
    pgroup.add_argument('--port', type=int,
                        help="port for kikusui PMX")
    pgroup.add_argument('--mode', type=str, default='acq', choices=['init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--sampling-frequency', type=float,
                        help="Sampling frequency for data acquisition")
    return parser


def main(args=None):
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPPMXAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    kwargs = {'ip': args.ip, 'port': args.port}
    if args.sampling_frequency is not None:
        kwargs['f_sample'] = args.sampling_frequency
    PMX = HWPPMXAgent(agent, **kwargs)

    agent.register_task('init_connection', PMX.init_connection, startup=init_params)
    agent.register_process('acq', PMX.acq, PMX._stop_acq)
    agent.register_task('set_on', PMX.set_on)
    agent.register_task('set_off', PMX.set_off)
    agent.register_task('set_i', PMX.set_i)
    agent.register_task('set_v', PMX.set_v)
    agent.register_task('set_i_lim', PMX.set_i_lim)
    agent.register_task('set_v_lim', PMX.set_v_lim)
    agent.register_task('use_ext', PMX.use_ext)
    agent.register_task('ign_ext', PMX.ign_ext)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
