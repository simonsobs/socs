import sys
import os
import argparse
import time

this_dir = os.path.dirname(__file__)

import src.C000DRD as c0
import src.JXC831 as jx
import src.control as ct
import src.gripper as gp
import src.command_gripper as cg

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

class GripperAgent:
    """Agent to control the three CHWP linear actuators

    Args:
        tcp_ip (str): IP address for gripper PLC
        tcp_port (str): Port for gripper PLC

    """
    def __init__(self, agent, tcp_ip, tcp_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False
        self.tcp_ip = tcp_ip
        self.tcp_port = int(tcp_port)
        self.log_file_path = os.path.join(this_dir, 'src', 'log_file.txt')

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwpgripper', record = True, agg_params = agg_params)

        self.PLC = c0.C000DRD(tcp_ip = self.tcp_ip, tcp_port = self.tcp_port)
        self.JXC = jx.JXC831(self.PLC)
        self.CTL = ct.Control(self.JXC)
        self.GPR = gp.Gripper(self.CTL)
        self.CMD = cg.Command(self.GPR)

    def grip_on(self, session, params = None):
        """grip_on(parmas = None)

        Turns on power to the grippers

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_on') as acquired:
            if not acquired:
                self.log.warn('Could not grip on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('ON'), 'Grippers on'

    def grip_off(self, session, params = None):
        """grip_off(parmas = None)

        Turns off power to the grippers

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_off') as acquired:
            if not acquired:
                self.log.warn('Could not grip off because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('OFF'), 'Grippers off'

#    @ocs_agent.param('state', default = 'ON', choices = ['ON', 'OFF'])
#    @ocs_agent.param('actuator', default = 0, choices = [0, 1, 2, 3])
    def grip_brake(self, session, params = None):
        """grip_brake(parmas = None)

        Turns on or off the gripper's EM brake

        Args:
            params (dict): Parameters dictionary for passing parameters to task

        Parameters:
            state (string): ON/OFF
            actuation (int): which actuator to turn the brake on/off for (0 is all three)

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_brake') as acquired:
            if not acquired:
                self.log.warn('Could not grip brake because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if params['actuator'] == 0:
                self.CMD.CMD('BRAKE ' + params['state'])
            else:
                self.CMD.CMD('BRAKE ' + params['state'] + ' ' + str(params['actuator']))

        return True, 'Gripper {} Brake {}'.format(params['actuator'], params['state'])

#    @ocs_agent.param('mode', default = 'PUSH', choices = ['PUSH', 'POS'])
#    @ocs_agent.param('actuator', default = 0, choices = [0, 1, 2, 3])
#    @ocs_agent.param('distance', default = 0., check = lambda x: -10. <= x <= 20.)
    def grip_move(self, session, params = None):
        """grip_move(parmas = None)

        Move the specified gripper the specified distance. The user choses between PUSHing mode or POSitioning
        mode. PUSHing moves slower and more acurately but can only move forward. POSitioning moves faster and in
        both directions. 

        Args:
            params (dict): Parameters dictionary for passing parameters to task

        Parameters:
            mode (string): PUSH or POS (push mode or positioning mode)
            actuator (int): which actuator to move (0 is all three)

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_move') as acquired:
            if not acquired:
                self.log.warn('Could not grip move because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.CMD.CMD('MOVE ' + params['mode'] + ' ' + str(params['actuator']) + ' ' + str(params['distance']))

        return True, 'Gripper {} moved {} mm via {}'.format(params['actuator'], params['distance'], params['mode'])

    def grip_home(self, session, params = None):
        """grip_home(parmas = None)

        Recalibrates and returns all three actuators to their home position

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_home') as acquired:
            if not acquired:
                self.log.warn('Could not grip home because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('HOME'), 'Grippers homed'

    def grip_inp(self, session, params = None):
        """grip_inp(parmas = None)

        Reads and prints from the actuator controller whether the grippers are currently in position

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_inp') as acquired:
            if not acquired:
                self.log.warn('Could not grip inp because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('INP'), 'Fetched INP'

    def grip_alarm(self, session, params = None):
        """grip_alarm(parmas = None)

        Reads and prints from the actuator controller the alarm state of the grippers

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_alarm') as acquired:
            if not acquired:
                self.log.warn('Could not grip alarm because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('ALARM'), 'Fetched ALARM'

    def grip_reset(self, session, params = None):
        """grip_reset(parmas = None)

        Clears any clearable alarm states from the actuator controller

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_reset') as acquired:
            if not acquired:
                self.log.warn('Could not grip reset because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('RESET'), 'Gripper alarm reset'

    def grip_position(self, session, params = None):
        """grip_position(parmas = None)

        Prints the current location of the grippers

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_position') as acquired:
            if not acquired:
                self.log.warn('Could not grip position because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('POSITION'), 'Fetched position'

#    @ocs_agent.param('actuator', default = 1, choices = [1, 2, 3])
#    @ocs_agent.param('distance', default = 0., check = lambda x: -10. <= x <= 20.)
    def grip_setpos(self, session, params = None):
        """grip_setpos(parmas = None)

        Manually sets actuator position stored in memory

        Args:
            params (dict): Parameters dictionary for passing parameters to task

        Parameters:
            actuator (int): which actuator to set the position (0 is all three)
            distance (float): actuator postion

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_setpos') as acquired:
            if not acquired:
                self.log.warn('Could not grip setpos because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.CMD.CMD('SETPOS ' + str(params['actuator']) + ' ' + str(params['distance']))

        return True, 'Gripper {} position recorded as {} mm'.format(params['actuator'], params['distance'])

    def grip_status(self, session, params = None):
        """grip_status(parmas = None)

        Prints all information bits from the actuator controller

        """
        with self.lock.acquire_timeout(timeout = 0, job = 'grip_status') as acquired:
            if not acquired:
                self.log.warn('Could not grip on because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return self.CMD.CMD('STATUS'), 'Fetched gripper status'

    def start_grip_acq(self, session, params = None):
        """start_grip_acq(parmas = None)

        Meathod to start gripper data acquisition process

        The most recent data collected is stored in the structure
            >>> data
            {'grip_pos_1': 0, 'grip_max_pos_err_1': 0,
            'grip_pos_2': 0, 'grip_max_pos_err_2': 0,
            'grip_pos_3': 0, 'grip_max_pos_err_3': 0}

        """
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

            data['data']['grip_max_pos_err_1'] = self.GPR.motors['1'].max_pos_err
            data['data']['grip_max_pos_err_2'] = self.GPR.motors['2'].max_pos_err
            data['data']['grip_max_pos_err_3'] = self.GPR.motors['3'].max_pos_err

            self.agent.publish_to_feed('hwpgripper', data)
            #self._log_info()
            time.sleep(0.2)

        self.agent.feeds['hwpgripper'].flush_buffer()
        return True, 'Acquisition exited cleanly'

    def stop_grip_acq(self, session, params = None):
        """
        Stops acq process
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data'

        return False, 'acq is not currently running'

    # Work in progress
    def _log_info(self):
        log_file = open(self.log_file_path, 'r+')
        
        lines = log_file.readlines()
        for line in lines:
            self.log.info(line)

        log_file.truncate(0)
        log_file.close()

def make_parser(parser = None):
    """
    Built the argument parser for the Agent. Allows sphinx to automatically build documentation
    baised on this function
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--tcp-ip')
    pgroup.add_argument('--tcp-port')
    return parser

if __name__ == '__main__':
    # Get the default ocs argument parser
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    # Parse the command line
    args = parser.parse_args()

    # Interpret options in the context of site_config
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
