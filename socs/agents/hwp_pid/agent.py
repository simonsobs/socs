import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet import reactor

import socs.agents.hwp_pid.drivers.pid_controller as pd


class HWPPIDAgent:
    """Agent to PID control the rotation speed of the CHWP

    Args:
        ip (str): IP address for the PID controller
        port (str): Port for the PID controller
        verbosity (str): Verbosity of PID controller output

    """

    def __init__(self, agent, ip, port, verbosity):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self._initialized = False
        self.take_data = False
        self.ip = ip
        self.port = port
        self._verbosity = verbosity > 0

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppid', record=True, agg_params=agg_params)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    @ocs_agent.param('force', default=False, type=bool)
    def init_connection(self, session, params):
        """init_connection(auto_acquire=False, force=False)

        **Task** - Initialize connection to PID
        Controller.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
            force (bool, optional): Force initialization, even if already
                initialized. Defaults to False.

        """
        if self._initialized and not params['force']:
            self.log.info("Connection already initialized. Returning...")
            return True, "Connection already initialized"

        with self.lock.acquire_timeout(10, job='init_connection') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run init_connection because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            try:
                self.pid = pd.PID(ip=self.ip, port=self.port,
                                  verb=self._verbosity)
                self.log.info('Connected to PID controller')
            except BrokenPipeError:
                self.log.error('Could not establish connection to PID controller')
                reactor.callFromThread(reactor.stop)
                return False, 'Unable to connect to PID controller'

        self._initialized = True

        # Start 'acq' Process if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Connection to PID controller established'

    def tune_stop(self, session, params):
        """tune_stop()

        **Task** - Reverse the drive direction of the PID controller and
        optimize the PID parameters for deceleration.

        """
        with self.lock.acquire_timeout(3, job='tune_stop') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not tune stop because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.tune_stop()

        return True, 'Reversing Direction'

    def tune_freq(self, session, params):
        """tune_freq()

        **Task** - Tune the PID controller setpoint to the rotation frequency
        and optimize the PID parameters for rotation.

        """
        with self.lock.acquire_timeout(3, job='tune_freq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not tune freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.tune_freq()

        return True, 'Tuning to setpoint'

    @ocs_agent.param('freq', default=0., check=lambda x: 0. <= x <= 3.0)
    def declare_freq(self, session, params):
        """declare_freq(freq=0)

        **Task** - Store the entered frequency as the PID setpoint when
        ``tune_freq()`` is next called.

        Parameters:
            freq (float): Desired HWP rotation frequency

        """
        with self.lock.acquire_timeout(3, job='declare_freq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not declare freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.declare_freq(params['freq'])

        return True, 'Setpoint at {} Hz'.format(params['freq'])

    @ocs_agent.param('p', default=0.2, type=float, check=lambda x: 0. < x <= 8.)
    @ocs_agent.param('i', default=63, type=int, check=lambda x: 0 <= x <= 200)
    @ocs_agent.param('d', default=0., type=float, check=lambda x: 0. <= x < 10.)
    def set_pid(self, session, params):
        """set_pid(p=0.2, i=63, d=0.)

        **Task** - Set the PID parameters. Note these changes are for the
        current session only and will change whenever the agent container is
        reloaded.

        Parameters:
            p (float): Proportional PID value
            i (int): Integral PID value
            d (float): Derivative PID value

        """
        with self.lock.acquire_timeout(3, job='set_pid') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set pid because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.set_pid(
                [params['p'], params['i'], params['d']])

        return True, f"Set PID params to p: {params['p']}, i: {params['i']}, d: {params['d']}"

    def get_freq(self, session, params):
        """get_freq()

        **Task** - Return the current HWP frequency as seen by the PID
        controller.

        """
        with self.lock.acquire_timeout(3, job='get_freq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            freq = self.pid.get_freq()
            session.data = {
                'freq': freq,
                'timestamp': time.time(),
            }

        return True, 'Current frequency = {}'.format(freq)

    def get_target(self, session, params):
        """get_target()

        **Task** - Return the target HWP frequency of the PID
        controller.

        """
        with self.lock.acquire_timeout(3, job='get_target') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            freq = self.pid.get_target()

        return True, 'Target frequency = {}'.format(freq)

    def get_direction(self, session, params):
        """get_direction()

        **Task** - Return the current HWP tune direction as seen by the PID
        controller.

        """
        with self.lock.acquire_timeout(3, job='get_direction') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            direction = self.pid.get_direction()
            session.data = {'direction': direction}

        return True, 'Current direction = {}'.format(['Forward', 'Reverse'][direction])

    @ocs_agent.param('direction', type=str, default='0', choices=['0', '1'])
    def set_direction(self, session, params):
        """set_direction(direction='0')

        **Task** - Set the HWP rotation direction.

        Parameters:
            direction (str): '0' for forward and '1' for reverse.

        """
        with self.lock.acquire_timeout(3, job='set_direction') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set direction because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.set_direction(params['direction'])

        return True, 'Set direction'

    @ocs_agent.param('slope', default=1., type=float, check=lambda x: -10. < x < 10.)
    @ocs_agent.param('offset', default=0.1, type=float, check=lambda x: -10. < x < 10.)
    def set_scale(self, session, params):
        """set_scale(slope=1, offset=0.1)

        **Task** - Set the PID's internal conversion from input voltage to
        rotation frequency.

        Parameters:
            slope (float): Slope of the "rotation frequency vs input voltage"
                relationship
            offset (float): y-intercept of the "rotation frequency vs input
                voltage" relationship

        """
        with self.lock.acquire_timeout(3, job='set_scale') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set scale because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.set_scale(params['slope'], params['offset'])

        return True, 'Set scale'

    def acq(self, session, params):
        """acq()

        **Process** - Start PID data acquisition.

        Notes:
            The most recent data collected is stored in the session data in the
            structure::

                >>> response.session['data']
                {'current_freq': 0,
                 'target_freq': 0,
                 'direction': 1,
                 'last_updated': 1649085992.719602}

        """
        with self.lock.acquire_timeout(timeout=10, job='acq') as acquired:
            if not acquired:
                self.log.warn('Could not start iv acq because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')
            last_release = time.time()
            self.take_data = True

            while self.take_data:
                # Relinquish sampling lock occasionally.
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                data = {'timestamp': time.time(),
                        'block_name': 'HWPPID', 'data': {}}

                try:
                    current_freq = self.pid.get_freq()
                    target_freq = self.pid.get_target()
                    direction = self.pid.get_direction()

                    data['data']['current_freq'] = current_freq
                    data['data']['target_freq'] = target_freq
                    data['data']['direction'] = direction
                except BaseException:
                    time.sleep(1)
                    continue

                self.agent.publish_to_feed('hwppid', data)

                session.data = {'current_freq': current_freq,
                                'target_freq': target_freq,
                                'direction': direction,
                                'last_updated': time.time()}

                time.sleep(5)

        self.agent.feeds['hwppid'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def _stop_acq(self, session, params):
        """
        Stop acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically build documentation
    baised on this function
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip')
    pgroup.add_argument('--port')
    pgroup.add_argument('--verbose', '-v', action='count', default=0,
                        help='PID Controller verbosity level.')
    pgroup.add_argument('--mode', type=str, default='acq',
                        choices=['init', 'acq'],
                        help="Starting operation for the Agent.")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPPIDAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    hwppid_agent = HWPPIDAgent(agent, ip=args.ip,
                               port=args.port,
                               verbosity=args.verbose)
    agent.register_task('init_connection', hwppid_agent.init_connection,
                        startup=init_params)
    agent.register_process('acq', hwppid_agent.acq,
                           hwppid_agent._stop_acq)
    agent.register_task('tune_stop', hwppid_agent.tune_stop)
    agent.register_task('tune_freq', hwppid_agent.tune_freq)
    agent.register_task('declare_freq', hwppid_agent.declare_freq)
    agent.register_task('set_pid', hwppid_agent.set_pid)
    agent.register_task('get_freq', hwppid_agent.get_freq)
    agent.register_task('get_target', hwppid_agent.get_target)
    agent.register_task('get_direction', hwppid_agent.get_direction)
    agent.register_task('set_direction', hwppid_agent.set_direction)
    agent.register_task('set_scale', hwppid_agent.set_scale)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
