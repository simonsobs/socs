import sys
import os
import argparse
import time

from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock

from socs.agent.pmx import PMX, Command

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    import src.pid_controller as pd


class RotationAgent:
    """Agent to control the rotation speed of the CHWP

    Args:
        kikusui_ip (str): IP address for the Kikusui power supply
        kikusui_port (str): Port for the Kikusui power supply
        pid_ip (str): IP address for the PID controller
        pid_port (str): Port for the PID controller

    """

    def __init__(self, agent, kikusui_ip, kikusui_port, pid_ip, pid_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False
        self.switching = False
        self.kikusui_ip = kikusui_ip
        self.kikusui_port = int(kikusui_port)
        self.pid_ip = pid_ip
        self.pid_port = pid_port

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwprotation', record=True, agg_params=agg_params)

        try:
            self.pmx = PMX(tcp_ip=self.kikusui_ip,
                           tcp_port=self.kikusui_port, timeout=0.5)
            self.cmd = Command(self.pmx)
            print('Connected to Kikusui power supply')
        except:
            print('Could not establish connection to Kikusui power supply')
            sys.exit(1)

        try:
            self.pid = pd.PID(pid_ip=self.pid_ip, pid_port=self.pid_port)
            print('Connected to PID controller')
        except:
            print('Could not establish connection to PID controller')
            sys.exit(1)

    def tune_stop(self, session, params):
        """tune_stop()

        **Task** - Reverse the drive direction of the PID controller and
        optimize the PID parameters for deceleration.

        """
        with self.lock.acquire_timeout(0, job='tune_stop') as acquired:
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
        with self.lock.acquire_timeout(0, job='tune_freq') as acquired:
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
        with self.lock.acquire_timeout(0, job='declare_freq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not declare freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.declare_freq(params['freq'])

        return True, 'Setpoint at {} Hz'.format(params['freq'])

    @ocs_agent.param('p_param', default=0.2, type=float, check=lambda x: 0. < x <= 8.)
    @ocs_agent.param('i_param', default=63, type=int, check=lambda x: 0 <= x <= 200)
    @ocs_agent.param('d_param', default=0., type=float, check=lambda x: 0. <= x < 10.)
    def set_pid(self, session, params):
        """set_pid(p_param=0.2, i_param=63, d_param=0.)

        **Task** - Set the PID parameters. Note these changes are for the
        current session only and will change whenever the agent container is
        reloaded.

        Parameters:
            p_param (float): Proportional PID value
            i_param (int): Integral PID value
            d_param (float): Derivative PID value

        """
        with self.lock.acquire_timeout(0, job='set_pid') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set pid because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.set_pid(
                [params['p_param'], params['i_param'], params['d_param']])

        return True, f"Set PID params to p: {params['p_param']}, i: {params['i_param']}, d: {params['d_param']}"

    def get_freq(self, session, params):
        """get_freq()

        **Task** - Return the current HWP frequency as seen by the PID
        controller.

        """
        with self.lock.acquire_timeout(0, job='get_freq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.get_freq()

        return self.pid.cur_freq, 'Current frequency = {}'.format(self.pid.cur_freq)

    def get_direction(self, session, params):
        """get_direction()

        **Task** - Return the current HWP tune direction as seen by the PID
        controller.

        """
        with self.lock.acquire_timeout(0, job='get_direction') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not get freq because {} is already running'.format(self.lock.job))

            self.pid.get_direction()

        return self.pid.direction, 'Current Direction = {}'.format(['Forward', 'Reverse'][self.pid.direction])

    @ocs_agent.param('direction', type=str, default='0', choices=['0', '1'])
    def set_direction(self, session, params):
        """set_direction(direction='0')

        **Task** - Set the HWP rotation direction.

        Parameters:
            direction (str): '0' for forward and '1' for reverse.

        """
        with self.lock.acquire_timeout(0, job='set_direction') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set direction because {} is already running'.format(self.lock.job))

            self.pid.set_direction(params['direction'])

        return True, 'Set direction'

    @ocs_agent.param('slope', default=1., type=float, check=lambda x: -10. < x < 10.)
    @ocs_agent.param('offset', default=0., type=float, check=lambda x: -10. < x < 10.)
    def set_scale(self, session, params):
        """set_scale(slope=1, offset=0)

        **Task** - Set the PID's internal conversion from input voltage to
        rotation frequency.

        Parameters:
            slope (float): Slope of the "rotation frequency vs input voltage"
                relationship
            offset (float): y-intercept of the "rotation frequency vs input
                voltage" relationship

        """
        with self.lock.acquire_timeout(0, job='set_scale') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set scale because {} is already running'.format(self.lock.job))

            self.pid.set_scale(params['slope'], params['offset'])

        return True, 'Set scale'

    def set_on(self, session, params):
        """set_on()

        **Task** - Turn on the Kikusui drive voltage.

        """
        with self.lock.acquire_timeout(0, job='set_on') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('on')
            self.switching = False

        return True, 'Set Kikusui on'

    def set_off(self, session, params):
        """set_off()

        **Task** - Turn off the Kikusui drive voltage.

        """
        with self.lock.acquire_timeout(0, job='set_off') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set off because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('off')
            self.switching = False

        return True, 'Set Kikusui off'

    @ocs_agent.param('volt', default=0, type=float, check=lambda x: 0 <= x <= 35)
    def set_v(self, session, params):
        """set_v(volt=0)

        **Task** - Set the Kikusui drive voltage.

        Parameters:
            volt (float): Kikusui set voltage

        """
        with self.lock.acquire_timeout(0, job='set_v') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set v because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('V {}'.format(params['volt']))
            self.switching = False

        return True, 'Set Kikusui voltage to {} V'.format(params['volt'])

    @ocs_agent.param('volt', default=32., type=float, check=lambda x: 0. <= x <= 35.)
    def set_v_lim(self, session, params):
        """set_v_lim(volt=32)

        **Task** - Set the Kikusui drive voltage limit.

        Parameters:
            volt (float): Kikusui limit voltage

        """
        with self.lock.acquire_timeout(0, job='set_v_lim') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not set v lim because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            print(params['volt'])
            self.cmd.user_input('VL {}'.format(params['volt']))
            self.switching = False

        return True, 'Set Kikusui voltage limit to {} V'.format(params['volt'])

    def use_ext(self, session, params):
        """use_ext()

        **Task** - Set the Kikusui to use an external voltage control. Doing so
        enables PID control.

        """
        with self.lock.acquire_timeout(0, job='use_ext') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not use external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('U')
            self.switching = False

        return True, 'Set Kikusui voltage to PID control'

    def ign_ext(self, session, params):
        """ign_ext()

        **Task** - Set the Kiksui to ignore external voltage control. Doing so
        disables the PID and switches to direct control.

        """
        with self.lock.acquire_timeout(0, job='ign_ext') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not ignore external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('I')
            self.switching = False

        return True, 'Set Kikusui voltage to direct control'

    def iv_acq(self, session, params):
        """iv_acq()

        **Process** - Start Kikusui data acquisition.

        Notes:
            The most recent data collected is stored in the session data in the
            structure::

                >>> response.session['data']
                {'kikusui_volt': 0,
                 'kikusui_curr': 0,
                 'last_updated': 1649085992.719602}

        """
        with self.lock.acquire_timeout(timeout=0, job='iv_acq') as acquired:
            if not acquired:
                self.log.warn('Could not start iv acq because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')

        self.take_data = True

        while self.take_data:
            data = {'timestamp': time.time(),
                    'block_name': 'HWPKikusui_IV', 'data': {}}

            if not self.switching:
                v_msg, v_val = self.cmd.user_input('V?')
                i_msg, i_val = self.cmd.user_input('C?')

                data['data']['kikusui_volt'] = v_val
                data['data']['kikusui_curr'] = i_val

                if type(data['data']['kikusui_curr']) == float and type(data['data']['kikusui_volt']) == float:
                    self.agent.publish_to_feed('hwprotation', data)

                session.data = {'kikusui_volt': v_val,
                                'kikusui_curr': i_val,
                                'last_updated': time.time()}

            time.sleep(1)

        self.agent.feeds['hwprotation'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def _stop_iv_acq(self, session, params):
        """
        Stop iv_acq process.
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
    pgroup.add_argument('--kikusui-ip')
    pgroup.add_argument('--kikusui-port')
    pgroup.add_argument('--pid-ip')
    pgroup.add_argument('--pid-port')
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='RotationAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    rotation_agent = RotationAgent(agent, kikusui_ip=args.kikusui_ip,
                                   kikusui_port=args.kikusui_port,
                                   pid_ip=args.pid_ip,
                                   pid_port=args.pid_port)
    agent.register_process('iv_acq', rotation_agent.iv_acq,
                           rotation_agent._stop_iv_acq, startup=True)
    agent.register_task('tune_stop', rotation_agent.tune_stop)
    agent.register_task('tune_freq', rotation_agent.tune_freq)
    agent.register_task('declare_freq', rotation_agent.declare_freq)
    agent.register_task('set_pid', rotation_agent.set_pid)
    agent.register_task('get_freq', rotation_agent.get_freq)
    agent.register_task('get_direction', rotation_agent.get_direction)
    agent.register_task('set_direction', rotation_agent.set_direction)
    agent.register_task('set_scale', rotation_agent.set_scale)
    agent.register_task('set_on', rotation_agent.set_on)
    agent.register_task('set_off', rotation_agent.set_off)
    agent.register_task('set_v', rotation_agent.set_v)
    agent.register_task('set_v_lim', rotation_agent.set_v_lim)
    agent.register_task('use_ext', rotation_agent.use_ext)
    agent.register_task('ign_ext', rotation_agent.ign_ext)

    runner.run(agent, auto_reconnect=True)
