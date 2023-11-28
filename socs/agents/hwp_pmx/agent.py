import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet import reactor

import socs.agents.hwp_pmx.drivers.PMX_ethernet as pmx
from socs.agents.hwp_supervisor.agent import get_op_data

txaio.use_twisted()


class HWPPMXAgent:
    """Agent for interfacing with a PMX Kikusui power supply
    to control the current and voltage that drive the rotation of the CHWP.

    Args:
        ip (str): IP address for the PMX Kikusui power supply
        port (str): Port for the PMX Kikusui power supply
        f_sample (float): sampling frequency (Hz)
        supervisor_id (str): Instance id of HWP supervisor
        no_data_timeout (float): Time (in seconds) to wait between receiving
            'no_data' actions from the supervisor and triggering a shutdown
    """

    def __init__(self, agent, ip, port, f_sample=1, supervisor_id=None,
                 no_data_timeout=15 * 60):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port

        self.f_sample = f_sample

        self._initialized = False
        self.take_data = False
        self.prot = 0

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppmx', record=True, agg_params=agg_params, buffer_time=1)

        self.agent.register_feed('rotation_action', record=True)

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

            self.dev.turn_off()
        return True, 'Set PMX Kikusui off'

    def clear_alarm(self, session, params):
        """clear_alarm()
        **Task** - Clear alarm and exit protection mode.
        """
        with self.lock.acquire_timeout(3, job='clear_alarm') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not clear alarm because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'
            self.dev.clear_alarm()
            self.prot = 0
        return True, 'Clear alarm'

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

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

            if self.shutdown_mode:
                return False, "Shutdown mode is in effect"

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
                 'prot': 0,
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

                try:
                    msg, curr = self.dev.meas_current()
                    data['data']['current'] = curr

                    msg, volt = self.dev.meas_voltage()
                    data['data']['voltage'] = volt

                    msg, code = self.dev.check_error()
                    data['data']['err_code'] = code
                    data['data']['err_msg'] = msg

                    prot_code = self.dev.check_prot()
                    if prot_code != 0:
                        self.prot = prot_code

                    prot_msg = self.dev.get_prot_msg(self.prot)
                    data['data']['prot_code'] = self.prot
                    data['data']['prot_msg'] = prot_msg

                    msg, src = self.dev.check_source()
                    data['data']['source'] = src
                except BaseException:
                    time.sleep(sleep_time)
                    continue

                self.agent.publish_to_feed('hwppmx', data)
                session.data = {'curr': curr,
                                'volt': volt,
                                'prot': self.prot,
                                'prot_msg': prot_msg,
                                'source': src,
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

    def initiate_shutdown(self, session, params):
        """ initiate_shutdown()

        **Task** - Initiate the shutdown of the agent.
        """
        self.log.warn("INITIATING SHUTDOWN")

        with self.lock.acquire_timeout(10, job='shutdown') as acquired:
            if not acquired:
                self.log.error("Could not acquire lock for shutdown.")
                return False, "Could not acquire lock."

            self.shutdown_mode = True
            self.dev.turn_off()

    def cancel_shutdown(self, session, params):
        """cancel_shutdown()

        **Task** - Cancels shutdown mode, allowing other tasks to update the power supply
        """
        self.shutdown_mode = False
        return True, "Cancelled shutdown mode"

    def monitor_supervisor(self, session, params):
        """monitor_supervisor()

        **Process** - This is a process that is constantly running to monitor the
        HWP supervisor and the recommended course of action
        course of action recommended by the HWP supervisor. If certain conditions
        are met, this will trigger a shutdown and force the power supply to
        power off.
        """

        session.set_status('running')
        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, "No supervisor ID set"

        while session.status in ['starting', 'running']:

            res = get_op_data(self.supervisor_id, 'monitor')
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['pmx']

            # If action is 'ok', update last_ok_time
            if action == 'ok':
                last_ok_time = time.time()

            # If action is 'no_data', check if last_ok_time, and potentially
            # trigger shutdown
            elif action == 'no_data':
                if (time.time() - last_ok_time) > self.no_data_timeout:
                    if not self.shutdown_mode:
                        self.agent.start('initiate_shutdown', params=None)

            # If action is 'shutdown', trigger shutdown
            elif action == 'stop':
                if not self.shutdown_mode:
                    self.agent.start('initiate_shutdown', params=None)

            data = {
                'data': {'rotation_action': action},
                'block_name': 'rotation_action',
                'timestamp': time.time()
            }

            self.agent.publish_to_feed('rotation_action', data)
            session.data = {
                'rotation_action': action,
                'time': time.time()
            }

            time.sleep(0.2)

        return True, 'Supervisor monitor has exited.'

    def _stop_monitor_supervisor(self, session, params):
        session.set_status('stopping')
        return True, "Stopping monitor shutdown."


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
    pgroup.add_argument('--supervisor-id', type=str,
                        help="Instance ID for HWP Supervisor agent")
    pgroup.add_argument('--no-data-timeout', type=float, default=15 * 60,
                        help="Time (sec) after which a 'no_data' action should "
                             "trigger a shutdown")
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

    kwargs = {'ip': args.ip, 'port': args.port,
              'supervisor_id': args.supervisor_id,
              'no_data_timeout': args.no_data_timeout, }
    if args.sampling_frequency is not None:
        kwargs['f_sample'] = args.sampling_frequency
    PMX = HWPPMXAgent(agent, **kwargs)

    agent.register_task('init_connection', PMX.init_connection, startup=init_params)
    agent.register_process('acq', PMX.acq, PMX._stop_acq)
    agent.register_process(
        'monitor_supervisor', PMX.monitor_supervisor, PMX._stop_monitor_supervisor,
        startup=True)
    agent.register_task('set_on', PMX.set_on)
    agent.register_task('set_off', PMX.set_off)
    agent.register_task('clear_alarm', PMX.clear_alarm)
    agent.register_task('set_i', PMX.set_i)
    agent.register_task('set_v', PMX.set_v)
    agent.register_task('set_i_lim', PMX.set_i_lim)
    agent.register_task('set_v_lim', PMX.set_v_lim)
    agent.register_task('use_ext', PMX.use_ext)
    agent.register_task('ign_ext', PMX.ign_ext)
    agent.register_task('initiate_shutdown', PMX.initiate_shutdown)
    agent.register_task('cancel_shutdown', PMX.cancel_shutdown)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
