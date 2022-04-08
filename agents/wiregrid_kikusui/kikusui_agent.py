import sys
import os
import argparse
import time
import numpy as np
import traceback

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    # import classes
    from src import pmx
    from src import command
    from src.common import openlog, writelog


class KikusuiAgent:
    """Agent to control the wire-grid rotation
    The KIKUSUI is a power supply and
    it is controlled via serial-to-ethernet converter.
    The converter is linked to the KIKUSUI
    via RS-232 (D-sub 9pin cable).
    The agent communicates with the converter via eternet.

    Args:
        kikusui-ip (str): IP address of the serial-to-ethernet converter
        kikusui-port (int or str): Asigned port for the KIKUSUI power supply
            The converter has four D-sub ports to control
            multiple devices connected via serial communication.
            Communicating device is determined
            by the ethernet port number of the converter.
        debug (bool): ON/OFF of writing a log file
    """
    def __init__(self, agent, kikusui_ip, kikusui_port, debug=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False
        self.kikusui_ip = kikusui_ip
        self.kikusui_port = int(kikusui_port)
        self.debug = debug

        self.position_path = '/data/wg-data/position.log'
        self.action_path = '/data/wg-data/action/'

        self.open_trial = 10
        self.Deg = 360/52000
        # self.feedback_time = [0.151, 0.241, 0.271, 0.301, 0.331]
        self.feedback_time = [0.151, 0.241, 0.271, 0.361, 0.451]
        self.feedback_cut = [1., 2., 3., 5.0, 8.0]
        self.feedback_steps = 8
        self.num_laps = 2
        self.stopped_time = 10
        self.agent_interval = 0.1

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'kikusui_psu', record=True, agg_params=agg_params)

        try:
            self.PMX = pmx.PMX(
                tcp_ip=self.kikusui_ip,
                tcp_port=self.kikusui_port,
                timeout=0.5)
        except Exception as e:
            self.log.warn(
                'Could not connect to serial converter! | Error = "%s"' % e)
            self.PMX = None

        if self.PMX is not None:
            self.cmd = command.Command(self.PMX)
        else:
            self.cmd = None

    ######################
    # Internal functions #
    ######################

    def _check_connect(self):
        if self.PMX is None:
            msg = 'No connection to the KIKUSUI power supply. | '\
                  'Error = "PMX is None"'
            self.log.warn(msg)
            return False, msg
        else:
            msg, ret = self.PMX.check_connect()
            if not ret:
                msg = 'No connection to the KIKUSUI power supply. | '\
                      'Error = "%s"' % msg
                self.log.warn(msg)
                return False, msg
        return True, 'Connection is OK.'

    def _reconnect(self):
        self.log.warn('Trying to reconnect...')
        # reconnect
        try:
            if self.PMX:
                del self.PMX
            if self.cmd:
                del self.cmd
            self.PMX = pmx.PMX(
                tcp_ip=self.kikusui_ip,
                tcp_port=self.kikusui_port,
                timeout=0.5)
        except Exception as e:
            msg = 'Could not reconnect to the KIKUSUI power supply! | '\
                  'Error: %s' % e
            self.log.warn(msg)
            self.PMX = None
            self.cmd = None
            return False, msg
        # reinitialize cmd
        self.cmd = command.Command(self.PMX)
        ret, msg = self._check_connect()
        if ret:
            msg = 'Successfully reconnected to the KIKUSUI power supply!'
            self.log.info(msg)
            return True, msg
        else:
            msg = 'Failed to reconnect to the KIKUSUI power supply!'
            self.log.warn(msg)
            if self.PMX:
                del self.PMX
            if self.cmd:
                del self.cmd
            self.PMX = None
            self.cmd = None
            return False, msg

    def _rotate_alittle(self, operation_time):
        if operation_time != 0.:
            self.cmd.user_input('ON')
            time.sleep(operation_time)
            self.cmd.user_input('OFF')
            time.sleep(self.agent_interval)
            return True, 'Successfully rotate a little!'
        return True, 'No rotation!'

    def _get_position(self, position_path, open_trial):
        try:
            for i in range(open_trial):
                with open(position_path) as f:
                    position_data = f.readlines()
                    position =\
                        position_data[-1].split(' ')[1].replace('\n', '')
                    if len(position) != 0:
                        break
        except Exception as e:
            with open('file_open_error.log', 'a') as f:
                traceback.print_exc(file=f)
            self.log.warn(
                'Failed to open ENCODER POSITION FILE | '
                '{}'.format(e)
                )

        return int(position)*self.Deg

    def _get_exectime(self, position_difference, feedback_cut, feedback_time):
        if position_difference >= feedback_cut[4]:
            operation_time = feedback_time[4]
        if (feedback_cut[4] > position_difference) &\
           (position_difference >= feedback_cut[3]):
            operation_time = feedback_time[3]
        if (feedback_cut[3] > position_difference) &\
           (position_difference >= feedback_cut[2]):
            operation_time = feedback_time[2]
        if (feedback_cut[2] > position_difference) &\
           (position_difference >= feedback_cut[1]):
            operation_time = feedback_time[1]
        if (feedback_cut[1] > position_difference) &\
           (position_difference >= feedback_cut[0]):
            operation_time = feedback_time[0]
        if feedback_cut[0] > position_difference:
            operation_time = 0.
        return operation_time

    def _move_next(self, logfile, feedback_steps, feedback_time):
        wanted_angle = 22.5
        uncertaity_cancel = 3
        absolute_position = np.arange(0, 360, wanted_angle)

        start_position = self._get_position(
            self.position_path, self.open_trial)
        if (360 < start_position + uncertaity_cancel):
            goal_position = wanted_angle
        elif absolute_position[-1] < start_position + uncertaity_cancel:
            goal_position = 0
        else:
            goal_position = min(
                absolute_position[np.where(
                    start_position + uncertaity_cancel < absolute_position)[0]
                ]
            )

        if self.debug:
            writelog(logfile, 'ON', 0, start_position, 'stepwise')

        self._rotate_alittle(feedback_time[-1]+0.1)
        time.sleep(self.agent_interval)

        for step in range(feedback_steps):
            mid_position = self._get_position(
                self.position_path, self.open_trial)
            if goal_position + wanted_angle < mid_position:
                operation_time =\
                    self._get_exectime(
                        goal_position - (mid_position - 360),
                        self.feedback_cut,
                        feedback_time)
            else:
                operation_time =\
                    self._get_exectime(
                        goal_position - mid_position,
                        self.feedback_cut,
                        feedback_time)

            if operation_time == 0.:
                break
            self._rotate_alittle(operation_time)

        if self.debug:
            writelog(logfile, 'OFF', 0,
                     self._get_position(
                        self.position_path, self.open_trial),
                     'stepwise')

    ##################
    # Main functions #
    ##################

    def set_on(self, session, params=None):
        """set_on()

        **Task** - Set output ON.

        """
        with self.lock.acquire_timeout(timeout=5, job='set_on') as acquired:
            if not acquired:
                self.log.warn('Could not set ON because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            logfile = openlog(self.action_path)
            if self.debug:
                writelog(logfile, 'ON', 0,
                         self._get_position(
                            self.position_path, self.open_trial),
                         'continuous')

            self.cmd.user_input('ON')
            logfile.close()
            return True, 'Set Kikusui on'

    def set_off(self, session, params=None):
        """set_off()

        **Task** - Set output OFF.

        """
        with self.lock.acquire_timeout(timeout=5, job='set_off') as acquired:
            if not acquired:
                self.log.warn('Could not set OFF because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            logfile = openlog(self.action_path)
            if self.debug:
                writelog(logfile, 'OFF', 0,
                         self._get_position(
                            self.position_path, self.open_trial),
                         'continuous')

            self.cmd.user_input('OFF')
            logfile.close()
            return True, 'Set Kikusui off'

    def set_c(self, session, params=None):
        """set_c(current=0)

        **Task** - Set current [A]

        Parameters:
            current (float): set current [A] (should be [0.0, 3.0])
        """
        if params is None:
            params = {}
        current = params.get('current', 0.)

        with self.lock.acquire_timeout(timeout=5, job='set_c') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run set_c() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            if current <= 3. and 0. <= current:
                self.cmd.user_input('C {}'.format(current))
            else:
                current = 3.0
                self.log.warn(
                    'Value Error: set current 3.0 A or less. '
                    'Now set to {} A'.format(current))
                self.cmd.user_input('C {}'.format(current))

            return True, 'Set Kikusui current to {} A'.format(current)

    def set_v(self, session, params=None):
        """set_v(volt=12)

        **Task** - Set voltage [V].

        Parameters:
            volt: set voltage [V] (Usually 12V)
        """
        if params is None:
            params = {}
        volt = params.get('volt', 12)

        with self.lock.acquire_timeout(timeout=5, job='set_v') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run set_v() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            if 0. <= volt and volt <= 12.:
                self.cmd.user_input('V {}'.format(volt))
            else:
                volt = 12.
                self.log.warn(
                    'Value Error: Rated Voltage of the motor is 12 V. '
                    'Now set to 12 V')
                self.cmd.user_input('V {}'.format(12.))

            return True, 'Set Kikusui voltage to {} V'.format(volt)

    def get_vc(self, session, params=None):
        """get_vc()

        **Task** - Show voltage [V], current [A], output on/off.

        """
        with self.lock.acquire_timeout(timeout=5, job='get_vc') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run get_vc() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            v_val = None
            c_val = None
            s_val = None
            msg = 'Error'
            s_msg = 'Error'

            # check connection
            ret, msg = self._check_connect()
            if not ret:
                msg = 'Could not get c,v because of failure of connection.'
            else:
                msg, v_val, c_val = self.cmd.user_input('VC?')
                s_msg, s_val = self.cmd.user_input('O?')

            self.log.info('Get voltage/current message: {}'.format(msg))
            self.log.info('Get status message: {}'.format(s_msg))
            return True,\
                'Get Kikusui voltage / current: {} V / {} A [status={}]'\
                .format(v_val, c_val, s_val)

    def calibrate_wg(self, session, params=None):
        """calibrate_wg(storepath='/data/wg-data/action/')

        **Task** - Run rotation-motor calibration for wire-grid.

        Parameters:
            storepath (str): Path for log file.
        """
        if params is None:
            params = {}
        storepath = params.get('storepath', self.action_path)

        with self.lock.acquire_timeout(timeout=5, job='calibrate_wg')\
                as acquired:
            if not acquired:
                self.log.warn('Could not run calibrate_wg() '
                              'because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            logfile = openlog(storepath)

            cycle = 1
            for i in range(11):
                tperiod = 0.10 + 0.02*i
                for j in range(100):
                    if j % 20 == 0:
                        self.log.warn(f'this is {cycle}th time action')

                    writelog(logfile, 'ON', tperiod,
                             self._get_position(
                                self.position_path, self.open_trial),
                             'calibration')
                    self._rotate_alittle(tperiod)
                    time.sleep(self.agent_interval+1.)
                    writelog(logfile, 'OFF', 0.,
                             self._get_position(
                                self.position_path, self.open_trial),
                             'calibration')
                    writelog(logfile, 'ON', 0.70,
                             self._get_position(
                                self.position_path, self.open_trial),
                             'calibration')
                    self._rotate_alittle(0.70)
                    time.sleep(self.agent_interval+1.)
                    writelog(logfile, 'OFF', 0.,
                             self._get_position(
                                self.position_path, self.open_trial),
                             'calibration')
                    cycle += 1

            logfile.close()

            return True,\
                'Micro step rotation of wire grid finished. '\
                'Please calibrate and take feedback params.'

    def stepwise_rotation(self, session, params=None):
        """stepwise_rotation(feedback_steps=8, num_laps=1, stopped_time=10, \
                             feedback_time=[0.181, 0.221, 0.251, 0.281, 0.301])

        **Task** - Run step-wise rotation for wire-grid calibration. In each
        step, seveal small-rotations are performed to rotate 22.5-deg.

        Parameters:
            feedback_steps (int): Number of small rotations for each 22.5-deg step.
            num_laps (int): Number of laps (revolutions).
            stopped_time (float): Stopped time [sec] for each 22.5-deg step.
            feedback_time (list): Calibration constants for the 22.5-deg rotation.
        """
        if params is None:
            params = {}

        with self.lock.acquire_timeout(timeout=5, job='stepwise_rotation')\
                as acquired:
            if not acquired:
                self.log.warn('Could not run stepwise_rotation() '
                              'because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            self.feedback_steps = params.get('feedback_steps', 8)
            self.num_laps = params.get('num_laps', 1)
            self.stopped_time = params.get('stopped_time', 10)
            self.feedback_time = params.get(
                'feedback_time', [0.181, 0.221, 0.251, 0.281, 0.301])

            logfile = openlog(self.action_path)

            for i in range(int(self.num_laps*16.)):
                self._move_next(
                    logfile, self.feedback_steps, self.feedback_time)
                time.sleep(self.stopped_time)

            logfile.close()

            return True, 'Step-wise rotation finished'

    def IV_acq(self, session, params=None):
        """IV_acq()

        **Process** - Run data acquisition.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {'fields':
                    {
                     'kikusui':
                        {'volt': voltage [V],
                         'curr': current [A],
                         'voltset': voltage setting [V],
                         'currset': current setting [A],
                         'status': output power status 1(on) or 0(off)
                         }
                    }
                }

        """

        # timeout is long because calibrate_wg will take a long time (> hours)
        with self.lock.acquire_timeout(timeout=1000, job='IV_acq') as acquired:
            if not acquired:
                self.log.warn('Could not run IV_acq '
                              'because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')

            self.take_data = True
            last_release = time.time()
            session.data = {'fields': {}}
            while self.take_data:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=1000):
                        self.log.warn(
                            'IV_acq(): '
                            'Could not re-acquire lock now held by {}.'
                            .format(self.lock.job))
                        if self.lock.job == 'calibrate_wg':
                            self.log.warn(
                                'IV_acq(): '
                                'Continue to wait for {}()'
                                .format(self.lock.job))
                            # Wait for lock acquisition forever
                            acquired = self.lock.acquire(
                                timeout=-1, job='IV_acq')
                            if acquired:
                                self.log.info(
                                    'Succcessfully got the lock '
                                    'for IV_acq()!')
                            else:
                                self.log.warn(
                                    'Failed to aquire the lock '
                                    'for IV_acq()!')
                                return False,\
                                    'Could not re-acquire lock '\
                                    'for IV_acq() (timeout=-1)'
                        else:
                            return False,\
                                'Could not re-acquire lock '\
                                'for IV_acq() (timeout=1000 sec)'

                current_time = time.time()
                data = {'timestamp': time.time(),
                        'block_name': 'Kikusui_IV',
                        'data': {}}

                # check connection
                ret, msg = self._check_connect()
                if not ret:
                    msg = 'Could not connect to the KIKUSUI power supply!'
                    v_val, i_val, vs_val, is_val = 0., 0., 0., 0.
                    s_val = -1  # -1 means Not connected.
                    self.log.warn(msg)
                    # try to reconnect
                    self._reconnect()
                else:
                    v_msg, v_val = self.cmd.user_input('V?')
                    i_msg, i_val = self.cmd.user_input('C?')
                    vs_msg, vs_val = self.cmd.user_input('VS?')
                    is_msg, is_val = self.cmd.user_input('CS?')
                    s_msg, s_val = self.cmd.user_input('O?')
                data['data']['kikusui_volt'] = v_val
                data['data']['kikusui_curr'] = i_val
                data['data']['kikusui_voltset'] = vs_val
                data['data']['kikusui_currset'] = is_val
                data['data']['kikusui_status'] = s_val
                self.agent.publish_to_feed('kikusui_psu', data)
                # store session.data
                field_dict = {'kikusui':
                              {'volt': v_val,
                               'curr': i_val,
                               'voltset': vs_val,
                               'currset': is_val,
                               'status': s_val
                               }
                              }
                session.data['timestamp'] = current_time
                session.data['fields'] = field_dict

                time.sleep(1)  # DAQ interval
            # End of while loop for take_data
        # End of acquired lock

        self.agent.feeds['kikusui_feed'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def stop_IV_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--kikusui-ip')
    pgroup.add_argument('--kikusui-port')
    pgroup.add_argument('--debug')
    pgroup.add_argument('--debug', dest='debug',
                        action='store_true', default=False,
                        help='Write a log file for debug')
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='WGKikusuiAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    kikusui_agent = KikusuiAgent(agent, kikusui_ip=args.kikusui_ip,
                                 kikusui_port=args.kikusui_port,
                                 debug=args.debug)
    agent.register_process('IV_acq', kikusui_agent.IV_acq,
                           kikusui_agent.stop_IV_acq, startup=True)
    agent.register_task('set_on', kikusui_agent.set_on)
    agent.register_task('set_off', kikusui_agent.set_off)
    agent.register_task('set_c', kikusui_agent.set_c)
    agent.register_task('set_v', kikusui_agent.set_v)
    agent.register_task('get_vc', kikusui_agent.get_vc)
    agent.register_task('calibrate_wg', kikusui_agent.calibrate_wg)
    agent.register_task('stepwise_rotation',
                        kikusui_agent.stepwise_rotation)

    runner.run(agent, auto_reconnect=True)
