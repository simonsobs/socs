import sys, os, argparse, time

this_dir = os.path.dirname(__file__)
sys.path.append(
        os.path.join(this_dir, 'src'))

import pid_controller as pd
import pmx as pm
import command as cm

from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock

class RotationAgent:
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
        self.agent.register_feed('HWPRotation', record = True, agg_params = agg_params)

        self.PMX = pm.PMX(tcp_ip = self.kikusui_ip, tcp_port = self.kikusui_port, timeout = 0.5)
        self.cmd = cm.Command(self.PMX)
        self.pid = pd.PID(pid_ip = self.pid_ip, pid_port = self.pid_port)
 
    def tune_stop(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'tune_stop') as acquired:
            if not acquired:
                self.log.warn('Could not tune stop because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.tune_stop()
        
        return True, 'Reversing Direction'

    def tune_freq(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'tune_freq') as acquired:
            if not acquired:
                self.log.warn('Could not tune freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.tune_freq()

        return True, 'Tuning to setpoint'

    def declare_freq(self, session, params = None):
        if params == None:
            params = {'freq': 0}

        with self.lock.acquire_timeout(0, job = 'declare_freq') as acquired:
            if not acquired:
                self.log.warn('Could not declare freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.declare_freq(params['freq'])

        return True, 'Setpoint at {} Hz'.format(params['freq'])

    def set_pid(self, session, params = None):
        if params == None:
            params = {'p_param': 0.2, 'i_param': 63, 'd_param': 0}

        with self.lock.acquire_timeout(0, job = 'set_pid') as acquired:
            if not acquired:
                self.log.warn('Could not set pid because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.set_pid([params['p_param'], params['i_param'], params['d_param']])

        return True, 'Set PID params to p: {}, i: {}, d: {}'.format(params['p_param'], params['i_param'], params['d_param'])

    def get_freq(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'get_freq') as acquired:
            if not acquired:
                self.log.warn('Could not get freq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.pid.get_freq()

        return self.pid.cur_freq, 'Current frequency = {}'.format(self.pid.cur_freq)

    def set_direction(self, session, params = None):
        if params == None:
            params = {'direction':'0'}

        with self.lock.acquire_timeout(0, job = 'set_direction') as acquired:
            if not acquired:
                self.log.warn('Could not set direction because {} is already runing'.format(self.lock.job))

            self.pid.set_direction(params['direction'])

        return True, 'Set direction'

    def set_on(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'set_on') as acquired:
            if not acquired:
                self.log.warn('Could not set on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('on')
            self.switching = False

        return True, 'Set Kikusui on'

    def set_off(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'set_off') as acquired:
            if not acquired:
                self.log.warn('Could not set off because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('off')
            self.switching = False

        return True, 'Set Kikusui off'

    def set_v(self, session, params = None):
        if params == None:
            params = {'volt': 0}

        with self.lock.acquire_timeout(0, job = 'set_v') as acquired:
            if not acquired:
                self.log.warn('Could not set v because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('V {}'.format(params['volt']))
            self.switching = False

        return True, 'Set Kikusui voltage to {} V'.format(params['volt'])

    def use_ext(self, session, params = None): 
        with self.lock.acquire_timeout(0, job = 'use_ext') as acquired:
            if not acquired:
                self.log.warn('Could not use external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('U')
            self.switching = False

        return True, 'Set Kikusui voltage to PID control'

    def ign_ext(self, session, params = None):
        with self.lock.acquire_timeout(0, job = 'ign_ext') as acquired:
            if not acquired:
                self.log.warn('Could not ignore external voltage because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.switching = True
            time.sleep(1)
            self.cmd.user_input('I')
            self.switching = False

        return True, 'Set Kikusui voltage to direct control'

    def start_IV_acq(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'IV_acq') as acquired:
            if not acquired:
                self.log.warn('Could not start IV acq because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')
        
        self.take_data = True

        while self.take_data:
            data = {'timestamp': time.time(), 'block_name': 'HWPKikusui_IV', 'data': {}}
            
            if not self.switching:
                v_msg, v_val = self.cmd.user_input('V?')
                i_msg, i_val = self.cmd.user_input('C?')

                data['data']['kikusui_volt'] = v_val
                data['data']['kikusui_curr'] = i_val
            else:
                data['data']['kikusui_volt'] = 0
                data['data']['kikusui_curr'] = 0

            self.agent.publish_to_feed('HWPRotation', data)
            time.sleep(1)

        self.agent.feeds['HWPRotation'].flush_buffer()
        return True, 'Acqusition exited cleanly'

    def stop_IV_acq(self, session, params = None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'

def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--kikusui-ip')
    pgroup.add_argument('--kikusui-port')
    pgroup.add_argument('--pid-ip')
    pgroup.add_argument('--pid-port')
    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'RotationAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    rotation_agent = RotationAgent(agent, kikusui_ip = args.kikusui_ip, 
                                          kikusui_port = args.kikusui_port,
                                          pid_ip = args.pid_ip,
                                          pid_port = args.pid_port)
    agent.register_process('IV_acq', rotation_agent.start_IV_acq,
                           rotation_agent.stop_IV_acq, startup = True)
    agent.register_task('tune_stop', rotation_agent.tune_stop)
    agent.register_task('tune_freq', rotation_agent.tune_freq)
    agent.register_task('declare_freq', rotation_agent.declare_freq)
    agent.register_task('set_pid', rotation_agent.set_pid) 
    agent.register_task('get_freq', rotation_agent.get_freq)  
    agent.register_task('set_direction', rotation_agent.set_direction) 
    agent.register_task('set_on', rotation_agent.set_on)
    agent.register_task('set_off', rotation_agent.set_off)
    agent.register_task('set_v', rotation_agent.set_v)
    agent.register_task('use_ext', rotation_agent.use_ext)
    agent.register_task('ign_ext', rotation_agent.ign_ext)

    runner.run(agent, auto_reconnect = True)

