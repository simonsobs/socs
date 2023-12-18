import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet import reactor

import socs.agents.hwp_pcu.drivers.hwp_pcu as pcu


class HWPPCUAgent:
    """Agent to phase compensation improve the CHWP motor efficiency

    Args:
        agent (ocs.ocs_agent.OCSAgent): Instantiated OCSAgent class for this agent
        port (str): Path to USB device in '/dev/'

    """

    def __init__(self, agent, port):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.initialized = False
        self.take_data = False
        self.port = port
        self.status = 'off'

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppcu', record=True, agg_params=agg_params)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    @ocs_agent.param('force', default=False, type=bool)
    def init_connection(self, session, params):
        """init_connection(auto_acquire=False, force=False)

        **Task** - Initialize connection to PCU
        Controller.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
            force (bool, optional): Force initialization, even if already
                initialized. Defaults to False.

        """
        if self.initialized and not params['force']:
            self.log.info("Connection already initialized. Returning...")
            return True, "Connection already initialized"

        with self.lock.acquire_timeout(3, job='init_connection') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run init_connection because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            try:
                self.PCU = pcu.PCU(port=self.port)
                self.log.info('Connected to PCU')
            except BrokenPipeError:
                self.log.error('Could not establish connection to PCU')
                reactor.callFromThread(reactor.stop)
                return False, 'Unable to connect to PCU'

        self.status = self.PCU.get_status()
        self.initialized = True

        # Start 'acq' Process if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Connection to PCU established'

    @ocs_agent.param('command', default='off', type=str, choices=['off', 'on_1', 'on_2', 'hold'])
    def send_command(self, session, params):
        """send_command(command)

        **Task** - Send commands to the phase compensation unit.
        off: The compensation phase is zero.
        on_1: The compensation phase is +120 deg.
        on_2: The compensation phase is -120 deg.
        hold: Stop the HWP spin.

        Parameters:
            command (str): set the operation mode from 'off', 'on_1', 'on_2' or 'hold'.

        """
        with self.lock.acquire_timeout(3, job='send_command') as acquired:
            if not acquired:
                self.log.warn('Could not send command because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            command = params['command']
            if command == 'off':
                off_channel = [0, 1, 2, 5, 6, 7]
                for i in off_channel:
                    self.PCU.relay_off(i)
                self.status = 'off'
                return True, 'Phase compensation is "off".'

            elif command == 'on_1':
                on_channel = [0, 1, 2]
                off_channel = [5, 6, 7]
                for i in on_channel:
                    self.PCU.relay_on(i)
                for i in off_channel:
                    self.PCU.relay_off(i)
                self.status = 'on_1'
                return True, 'Phase compensation operates "on_1".'

            elif command == 'on_2':
                on_channel = [0, 1, 2, 5, 6, 7]
                for i in on_channel:
                    self.PCU.relay_on(i)
                self.status = 'on_2'
                return True, 'Phase compensation operates "on_2".'

            elif command == 'hold':
                on_channel = [0, 1, 2, 5]
                off_channel = [6, 7]
                for i in on_channel:
                    self.PCU.relay_on(i)
                for i in off_channel:
                    self.PCU.relay_off(i)
                self.status = 'hold'
                return True, 'Phase compensation operates "hold".'

            else:
                return True, "Choose the command from 'off', 'on_1', 'on_2' and 'hold'."

    def get_status(self, session, params):
        """get_status()

        **Task** - Return the status of the PCU.

        """
        with self.lock.acquire_timeout(3, job='get_status') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get status because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.status = self.PCU.get_status()

        return True, 'Current status is ' + self.status

    def acq(self, session, params):
        """acq()

        **Process** - Start PCU data acquisition.

        Notes:
            The most recent data collected is stored in the session data in the
            structure::

                >>> response.session['data']
                {'status': 'on_1',
                 'last_updated': 1649085992.719602}

        """
        with self.lock.acquire_timeout(timeout=3, job='acq') as acquired:
            if not acquired:
                self.log.warn('Could not start pcu acq because {} is already running'
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
                        'block_name': 'hwppcu', 'data': {}}

                # status = self.PCU.get_status()
                status = self.status
                data['data']['status'] = status

                self.agent.publish_to_feed('hwppcu', data)

                session.data = {'status': status,
                                'last_updated': time.time()}

                time.sleep(5)

        self.agent.feeds['hwppcu'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def _stop_acq(self, session, params):
        """
        Stop acq process.
        """
        if self.take_data:
            self.PCU.close()
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
    pgroup.add_argument('--port', type=str, help="Path to USB node for the lakeshore")
    pgroup.add_argument('--mode', type=str, default='acq',
                        choices=['init', 'acq'],
                        help="Starting operation for the Agent.")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPPCUAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    hwppcu_agent = HWPPCUAgent(agent,
                               port=args.port)
    agent.register_task('init_connection', hwppcu_agent.init_connection,
                        startup=init_params)
    agent.register_process('acq', hwppcu_agent.acq,
                           hwppcu_agent._stop_acq)
    agent.register_task('send_command', hwppcu_agent.send_command)
    agent.register_task('get_status', hwppcu_agent.get_status)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
