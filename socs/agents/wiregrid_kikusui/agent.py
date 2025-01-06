import argparse
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_client import OCSClient
from ocs.ocs_twisted import TimeoutLock

from socs.agents.wiregrid_kikusui.drivers.common import openlog, writelog
from socs.common import pmx


class WiregridKikusuiAgent:
    """Agent to control the wire-grid rotation
    The KIKUSUI is a power supply and
    it is controlled via serial-to-ethernet converter.
    The converter is linked to the KIKUSUI
    via RS-232 (D-sub 9pin cable).
    The agent communicates with the converter via eternet.

    Args:
        kikusui_ip (str): IP address of the serial-to-ethernet converter
        kikusui_port (int or str): Asigned port for the KIKUSUI power supply
            The converter has four D-sub ports to control
            multiple devices connected via serial communication.
            Communicating device is determined
            by the ethernet port number of the converter.
        encoder_agent (str): Instance ID of the wiregrid encoder agent
        debug (bool): ON/OFF of writing a log file
    """

    def __init__(self, agent, kikusui_ip, kikusui_port,
                 encoder_agent='wgencoder', debug=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False
        self.kikusui_ip = kikusui_ip
        self.kikusui_port = int(kikusui_port)
        self.encoder_agent = encoder_agent
        self.debug = debug

        self.debug_log_path = '/data/wg-data/action/'

        self.open_trial = 10
        self.Deg = 360 / 52000
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
            self.cmd = pmx.Command(self.PMX)
        else:
            self.cmd = None

        # Connect to the encoder agent
        self.encoder_clident = None
        self._connect_encoder()

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
        self.cmd = pmx.Command(self.PMX)
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

    def _connect_encoder(self):
        self.encoder_client = OCSClient(self.encoder_agent)

    def _rotate_alittle(self, operation_time):
        if operation_time != 0.:
            self.cmd.user_input('ON')
            time.sleep(operation_time)
            self.cmd.user_input('OFF')
            time.sleep(self.agent_interval)
            return True, 'Successfully rotate a little!'
        return True, 'No rotation!'

    def _get_position(self):
        position = -1.
        try:
            response = self.encoder_client.acq.status()
        except Exception as e:
            self.log.warn(
                'Failed to get ENCODER POSITION | '
                '{}'.format(e)
            )
            self.log.warn(
                '    --> Retry to connect to the encoder agent'
            )
            self._connect_encoder()
            try:
                response = self.encoder_client.acq.status()
            except Exception as e:
                self.log.error(
                    'Failed to get encoder position | '
                    '{}'.format(e)
                )
                return -1.

        try:
            position = (float)(
                response.session['data']['fields']['encoder_data']['reference_degree'][-1])
        except Exception as e:
            self.log.warn(
                'Failed to get encoder position | '
                '{}'.format(e)
            )

        return position

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

        start_position = self._get_position()
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

        self._rotate_alittle(feedback_time[-1] + 0.1)
        time.sleep(self.agent_interval)

        for step in range(feedback_steps):
            mid_position = self._get_position()
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
                     self._get_position(), 'stepwise')

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

            if self.debug:
                logfile = openlog(self.debug_log_path)
                writelog(logfile, 'ON', 0,
                         self._get_position(), 'continuous')
                logfile.close()

            self.cmd.user_input('ON')
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

            if self.debug:
                logfile = openlog(self.debug_log_path)
                writelog(logfile, 'OFF', 0,
                         self._get_position(), 'continuous')
                logfile.close()

            self.cmd.user_input('OFF')
            return True, 'Set Kikusui off'

    @ocs_agent.param('current', default=0., type=float,
                     check=lambda x: 0.0 <= x <= 4.9)
    def set_c(self, session, params):
        """set_c(current=0)

        **Task** - Set current [A]

        Parameters:
            current (float): set current [A] (should be [0.0, 4.9])
        """
        current = params.get('current')

        with self.lock.acquire_timeout(timeout=5, job='set_c') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run set_c() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            self.cmd.user_input('C {}'.format(current))
            return True, 'Set Kikusui current to {} A'.format(current)

    @ocs_agent.param('volt', default=12., type=float,
                     check=lambda x: 0.0 <= x <= 12.0)
    def set_v(self, session, params):
        """set_v*volt=12.)

        **Task** - Set voltage [V].

        Parameters:
            volt: set voltage [V] (Usually 12V / Should be [0.0, 12.0])
        """
        volt = params.get('volt')

        with self.lock.acquire_timeout(timeout=5, job='set_v') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run set_v() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            self.cmd.user_input('V {}'.format(volt))

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
                self.log.warn(msg)
            else:
                v_val, c_val = self.cmd.user_input('VC?')
                s_msg, s_val = self.cmd.user_input('O?')

            return True, \
                'Get Kikusui voltage / current: {} V / {} A [status={}]'\
                .format(v_val, c_val, s_val)

    def get_angle(self, session, params=None):
        """get_angle()

        **Task** - Show wire-grid rotaiton angle [deg].

        """
        with self.lock.acquire_timeout(timeout=5, job='get_angle') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run get_angle() because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock'

            angle = self._get_position()
            if angle < 0.:
                return False, \
                    'Could not get the angle of the wire-grid rotation.'

            return True, \
                'Get wire-grid rotation angle = {} deg'.format(angle)

    def calibrate_wg(self, session, params=None):
        """calibrate_wg()

        **Task** - Run rotation-motor calibration for wire-grid.

        """

        with self.lock.acquire_timeout(timeout=5, job='calibrate_wg')\
                as acquired:
            if not acquired:
                self.log.warn('Could not run calibrate_wg() '
                              'because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            logfile = openlog(self.debug_log_path)

            cycle = 1
            for i in range(11):
                tperiod = 0.10 + 0.02 * i
                for j in range(100):
                    if j % 20 == 0:
                        self.log.warn(f'this is {cycle}th time action')

                    writelog(logfile, 'ON', tperiod,
                             self._get_position(), 'calibration')
                    self._rotate_alittle(tperiod)
                    time.sleep(self.agent_interval + 1.)
                    writelog(logfile, 'OFF', 0.,
                             self._get_position(), 'calibration')
                    writelog(logfile, 'ON', 0.70,
                             self._get_position(), 'calibration')
                    self._rotate_alittle(0.70)
                    time.sleep(self.agent_interval + 1.)
                    writelog(logfile, 'OFF', 0.,
                             self._get_position(), 'calibration')
                    cycle += 1

            logfile.close()

            return True, \
                'Micro step rotation of wire grid finished. '\
                'Please calibrate and take feedback params.'

    def stepwise_rotation(self, session, params=None):
        """stepwise_rotation(feedback_steps=8, num_laps=1, stopped_time=10, \
                             feedback_time=[0.181, 0.221, 0.251, 0.281, 0.301])

        **Task** - Run step-wise rotation for wire-grid calibration. In each
        step, seveal small-rotations are performed to rotate 22.5-deg.

        Parameters:
            feedback_steps (int): Number of small rotations
                                  for each 22.5-deg step.
            num_laps (int): Number of laps (revolutions).
            stopped_time (float): Stopped time [sec]
                                  for each 22.5-deg step.
            feedback_time (list): Calibration constants
                                  for the 22.5-deg rotation.
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

            if self.debug:
                logfile = openlog(self.debug_log_path)
            else:
                logfile = None

            for i in range(int(self.num_laps * 16.)):
                self._move_next(
                    logfile, self.feedback_steps, self.feedback_time)
                time.sleep(self.stopped_time)

            if self.debug:
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
                    },
                 'timestamp':1601925677.6914878
                }

        """

        # timeout is long because calibrate_wg will take a long time (> hours)
        with self.lock.acquire_timeout(timeout=1000, job='IV_acq') as acquired:
            if not acquired:
                self.log.warn('Could not run IV_acq '
                              'because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

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
                                return False, \
                                    'Could not re-acquire lock '\
                                    'for IV_acq() (timeout=-1)'
                        else:
                            return False, \
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
                session.data['fields'] = field_dict
                session.data['timestamp'] = current_time

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
    pgroup.add_argument('--encoder-agent', dest='encoder_agent',
                        default='wgencoder',
                        help='Instance id of the wiregrid encoder agent')
    pgroup.add_argument('--debug', dest='debug',
                        action='store_true', default=False,
                        help='Write a log file for debug')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='WiregridKikusuiAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    kikusui_agent = WiregridKikusuiAgent(agent, kikusui_ip=args.kikusui_ip,
                                         kikusui_port=args.kikusui_port,
                                         encoder_agent=args.encoder_agent,
                                         debug=args.debug)
    agent.register_process('IV_acq', kikusui_agent.IV_acq,
                           kikusui_agent.stop_IV_acq, startup=True)
    agent.register_task('set_on', kikusui_agent.set_on)
    agent.register_task('set_off', kikusui_agent.set_off)
    agent.register_task('set_c', kikusui_agent.set_c)
    agent.register_task('set_v', kikusui_agent.set_v)
    agent.register_task('get_vc', kikusui_agent.get_vc)
    agent.register_task('get_angle', kikusui_agent.get_angle)
    agent.register_task('calibrate_wg', kikusui_agent.calibrate_wg)
    agent.register_task('stepwise_rotation',
                        kikusui_agent.stepwise_rotation)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
