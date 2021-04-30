import sys, os, argparse, time

this_dir = os.path.dirname(__file__)
sys.path.append(
        os.path.join(this_dir, 'src'))

import src.C000DRD as c0
import src.JXC831 as jx
import src.control as ct
import src.gripper as gp
import src.command_gripper as cd

from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock

class GripperAgent:
    def __init__(self, agent, tcp_ip, tcp_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False
        self.tcp_ip = tcp_ip
        self.tcp_port = int(tcp_port)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('HWPGripper', record = True, agg_params = agg_params)

        self.PLC = c0.C000DRD(tcp_ip = self.tcp_ip, tcp_port = self.tcp_port)
        self.JXC = jx.JXC831(self.PLC)
        self.CTL = ct.Control(self.JXC)
        self.GPR = gp.Gripper(self.CTL)
        self.CMD = cd.Command(self.GPR)

    def grip_on(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_on') as acquired:
            if not acquired:
                self.log.warn('Could not grip on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('ON'), 'Grippers on'

    def grip_off(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_off') as acquired:
            if not acquired:
                self.log.warn('Could not grip off because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('OFF'), 'Grippers off'

    def grip_brake(self, session, params = None):
        if params == None:
            params = {'state': 'ON', 'actuator': 0}
        
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_brake') as acquired:
            if not acquired:
                self.log.warn('Could not grip brake because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if params['actuator'] == 0:
                self.CMD.CMD('BRAKE ' + params['state'])
            else:
                self.CMD.CMD('BRAKE ' + params['state'] + ' ' + str(params['actuator']))

        return True, 'Gripper {} Brake {}'.format(params['actuator'], params['state'])

    def grip_move(self, session, params = None):
        if params == None:
            params = {'mode': 'PUSH', 'actuator': 1, 'distance': 0}
        
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_move') as acquired:
            if not acquired:
                self.log.warn('Could not grip move because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.CMD.CMD('MOVE ' + params['mode'] + ' ' + str(params['actuator']) + ' ' + str(params['distance']))

        return True, 'Gripper {} moved {} mm via {}'.format(params['actuator'], params['distance'], params['mode'])

    def grip_home(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_home') as acquired:
            if not acquired:
                self.log.warn('Could not grip home because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('HOME'), 'Grippers homed'

    def grip_inp(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_inp') as acquired:
            if not acquired:
                self.log.warn('Could not grip inp because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('INP'), 'Fetched INP'

    def grip_alarm(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_alarm') as acquired:
            if not acquired:
                self.log.warn('Could not grip alarm because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('ALARM'), 'Fetched ALARM'

    def grip_reset(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_reset') as acquired:
            if not acquired:
                self.log.warn('Could not grip reset because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('RESET'), 'Gripper alarm reset'

    def grip_position(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_position') as acquired:
            if not acquired:
                self.log.warn('Could not grip position because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('POSITION'), 'Fetched position'

    def grip_setpos(self, session, params = None):
        if params == None:
            params = {'actuator': 1, 'distance': 0}

        with self.lock.acquire_timeout(timeout = 0, job = 'grip_setpos') as acquired:
            if not acquired:
                self.log.warn('Could not grip setpos because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.CMD.CMD('SETPOS ' + params['actuator'] + ' ' + params['distance'])

        return True, 'Gripper {} position recorded as {} mm'.format(params['actuator'], params['distance'])

    def grip_status(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_status') as acquired:
            if not acquired:
                self.log.warn('Could not grip on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('STATUS'), 'Fetched gripper status'

    def start_grip_acq(self, session, params = None):
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_acq') as acquired:
            if not acquired:
                self.log.warn('Could not start grip acq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            session.set_status('running')
            self.take_data = True

        while self.take_data:
            data = {'timestamp': time.time(), 'block_name': 'Gripper_POS', 'data': {}}

            data['data']['grip_pos_1'] = self.GPR.motors['1'].pos
            data['data']['grip_pos_2'] = self.GPR.motors['2'].pos
            data['data']['grip_pos_3'] = self.GPR.motors['3'].pos

            self.agent.publish_to_feed('HWPGripper', data)
            time.sleep(1)

        self.agent.feeds['HWPGripper'].flush_buffer()
        return True, 'Acquisition exited cleanly'

    def stop_grip_acq(self, session, params = None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'

def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--tcp-ip')
    pgroup.add_argument('--tcp-port')
    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'GripperAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    gripper_agent = GripperAgent(agent, tcp_ip = args.tcp_ip, tcp_port = args.tcp_port)

    agent.register_task('grip_on', gripper_agent.grip_on)
    agent.register_task('grip_off', gripper_agent.grip_off)
    agent.register_task('grip_brake', gripper_agent.grip_brake)
    agent.register_task('grip_move', gripper_agent.grip_move)
    agent.register_task('grip_home', gripper_agent.grip_home)
    agent.register_task('grip_inp', gripper_agent.grip_inp)
    agent.register_task('grip_alarm', gripper_agent.grip_alarm)
    agent.register_task('grip_reset', gripper_agent.grip_reset)
    agent.register_task('grip_position', gripper_agent.grip_position)
    agent.register_task('grip_setpos', gripper_agent.grip_setpos)
    agent.register_task('grip_status', gripper_agent.grip_status)
    agent.register_process('grip_acq', gripper_agent.start_grip_acq,
                           gripper_agent.stop_grip_acq, startup = True)

    runner.run(agent, auto_reconnect = True)
