#!/usr/bin/env python3

import sys
import os
import argparse
import time
import subprocess
import numpy as np
import signal
import ctypes
import multiprocessing

this_dir = os.path.dirname(__file__)
sys.path.append(
        os.path.join(this_dir, 'src'))
sys.path.append(
        os.path.join(this_dir, 'pru'))

import gripper_client as gclient
import GripperCollector as gc
import GripperBuilder as gb

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TImeoutLock

class GripperAgent:
    def __init__(self, agent, mcu_ip, pru_port, control_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.mcu_ip = mcu_ip
        self.pru_port = pru_port
        self.control_port = control_port

        self.collector = gc.GripperCollector(self.pru_port)
        self.builder = gb.GripperBuilder(self.collector)

        self.last_encoder = 0
        self.last_limit = 0
        self.last_limit_time = 0
        self.is_forced = False
        
        self.encoder_names = ['Actuator 1 A', 'Actuator 1 B', 'Actuator 2 A',
                              'Actuator 2 B', 'Actuator 3 A', 'Actuator 3 B']
        self.encoder_pru = [0,1,2,3,4,5]
        self.encoder_edges = multiprocessing.Array(ctypes.c_int, (0,0,0,0,0,0))
        self.encoder_direction = multiprocessing.Array(ctypes.c_int, (1,1,1,1,1,1))

        self.limit_names = ['Actuator 1 Cold', 'Actuator 1 Warm', 'Actuator 2 Cold',
                            'Actuator 2 Warm', 'Actuator 3 Cold', 'Actuator 3 Warm']
        self.limit_pru = [8,9,10,11,12,13]
        self.limit_state = [0,0,0,0,0,0]

        self.command = multiprocessing.Array('c', b'                ')

        self._should_stop = multiprocessing.Value(ctypes.c_bool, False)
        self._stopped = multiprocessing.Value(ctypes.c_bool, False)
        self.mode = multiprocessing.Value(ctypes.c_bool, False)
        self.force = multiprocessing.Value(ctypes.c_bool, False)

        self._process = multiprocessing.Process(
                    target = self.process_data,
                    args = (self._should_stop, self._stopped))
        self._process.start()
        signal.signal(signal.SIGINT, self.sigint_handler_parent)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwpgripper', record = True, agg_params = agg_params)

    def process_data(self, should_stop, stopped):
        signal.signal(signal.SIGINT, self.sigint_handler_child)

        self.client = gclient.GripperClient(self.mcu_ip, self.control_port)
        self.client.send_data('EMG ON')

        while True:
            if should_stop.value:
                break

            encoder_data = self.builder.process_packets()
            if len(encoder_data['state']):
                edges = np.concatenate(([self.last_encoder ^ encoder_data['state'][0]],
                                        encoder_data['state'][1:] ^ encoder_data['state'][:-1]))

                with self.encoder_edges.get_lock():
                    with self.encoder_direction.get_lock():
                        for index, pru in enumerate(self.encoder_pru):
                            self.encoder_edges[index] += \
                                    self.encoder_direction[index]*np.sum((edges >> pru) & 1)

                self.last_encoder = encoder_data['state'][-1]


            clock, state = self.builder.limit_state[0], int(self.builder.limit_state[1])
    
            for index, pru in enumerate(self.limit_pru):
                self.limit_state[index] = ((state & (1 << pru)) >> pru)

            if (state and not self.mode.value) or self.limit_state[0] or self.limit_state[2] or self.limit_state[4]:
                self.last_limit_time = time.time()
                if self.force.value and not self.is_forced:
                    self.client.send_data('EMG ON')
                    self.is_forced = True
                elif self.last_limit != state and not self.force.value:
                    self.last_limit = state

                    if (self.limit_state[1] and not self.mode.value) or self.limit_state[0]:
                        self.client.send_data('EMG OFF 1')
                    else:
                        self.client.send_data('EMG ON 1')

                    if (self.limit_state[3] and not self.mode.value) or self.limit_state[2]:
                        self.client.send_data('EMG OFF 2')
                    else:
                        self.client.send_data('EMG ON 2')
                
                    if (self.limit_state[5] and not self.mode.value) or self.limit_state[4]:
                        self.client.send_data('EMG OFF 3')
                    else:
                        self.client.send_data('EMG ON 3')

                    print('Limit switch activation at clock: {}'.format(clock))
                    for index, name in enumerate(self.limit_names):
                        if self.limit_state[index]:
                            print('{} activated'.format(name))
            else:
                if time.time() - self.last_limit_time > 5:
                    if self.last_limit != 0:
                        self.client.send_data('EMG ON')
                        self.last_limit = 0
        
            if self.command.value != b'                ':
                with self.command.get_lock():
                    command_raw = self.command.value.decode(encoding = 'UTF-8')
                    self.client.send_data(command_raw)
                    self.command.value = b'                ' 

        with stopped.get_lock():
            stopped.value = True

    def sigint_handler_parent(self, signal, frame):
        self.stop()
        self.builder._collector.stop()
        sys.exit()

    def sigint_handler_child(self, signal, frame):
        pass

    def stop(self):
        with self._should_stop.get_lock():
            self._should_stop.value = True

        while not self._stopped.value:
            time.sleep(0.001)
        self._process.terminate()
        self._process.join()

    def grip_on(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_on') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = b'ON'

        return True, 'Power on'

    def grip_off(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_off') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'
            
            with self.command.get_lock():
                self.command.value = b'OFF'
    
        return True, 'Power off'

    @ocs_agent.param('state', default = 'ON', type = str)
    @ocs_agent.param('actuator', default = 0, type = int, check = lambda x: 0 <= x <= 3)
    def grip_brake(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_brake') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                if actuator == 0:
                    self.command.value = bytes('BRAKE ' + params['state'], 'utf-8')
                else:
                    self.command.value = bytes('BRAKE ' + params['state'] + ' ' + str(params['actuator']), 'utf-8')

        return True, 'Changed brake state'

    
    @ocs_agent.param('mode', default = 'PUSH', type = str)
    @ocs_agent.param('actuator', default = 1, type = int, check = lambda x: 1 <= x <= 3)
    @ocs_agent.param('distance', default = 0, type = float, check = lambda x: -10. <= x <= 10.)
    def grip_move(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_move') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            pru_chains = [2*params['actuator'] - 2, 2*params['actuator'] - 1]
            with self.encoder_direction.get_lock():
                for chain in pru_chains:
                    if params['distance'] >= 0:
                        self.encoder_direction[chain] = 1
                    elif params['distance'] < 0:
                        self.encoder_direction[chain] = -1

            with self.command.get_lock():
                self.command.value = bytes('MOVE ' + params['mode'] + ' ' + str(params['actuator']) + \
                                            ' ' + str(params['distance']), 'utf-8')

        return True, 'Moved actuators'

    def grip_home(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_home') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = b'HOME'
        

            with self.encoder_edges.get_lock():
                for index, _ in enumerate(self.encoder_edges):
                    self.encoder_edges[index] = 0

        return True, 'Homed actuators'

    def grip_inp(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_inp') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = b'INP'

        return True, 'Queried are actuators in known state'

    def grip_alarm(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_alarm') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = b'ALARM'

        return True, 'Queried alarm state'

    def grip_reset(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_reset') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = b'RESET'

        return True, 'Reset alarm state'

    @ocs_agent.param('actuator', default = 1, type = int, check = lambda x: 1 <= x <= 3)
    def grip_act(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_act') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.command.get_lock():
                self.command.value = bytes('ACT ' + str(params['actuator']), 'utf-8')

        return True, 'Queried actuator connection'

    @ocs_agent.param('value', default = False, type = bool)
    def grip_mode(self, session, params = None):
        with self.lock.aquire_timeout(0, job = 'grip_mode') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            with self.mode.get_lock():
                self.mode.value = params['value']

        return True, 'Changed temperature mode'

    @ocs_agent.param('value', default = False, type = bool)
    def grip_force(self, value):
        with self.lock.aquire_timeout(0, job = 'grip_force') as aquired:
            if not aquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not aquire lock'

            if params['value']:
                self.is_forced = False

            with self.force.get_lock():
                self.force.value = params['value']

        return True, 'Changed force parameter'

    # To be implemented
    def start_grip_acq(self):
        pass

    # To be implemented
    def stop_grip_acq(self):
        pass

    # Not completed
    def _get_pos(self):
        slope = 1
        return [rising_edges*slope for rising_edges in self.encoder_edges]

def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()
    
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--mcu_ip')
    pgroup.add_argument('--pru_port')
    pgroup.add_argument('--control_port')
    return parser

if __name__ == '__main__':
    site_parser = site.config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'GripperAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    gripper_agent = GripperAgent(agent, mcu_ip = args.mcu_ip
                                        pru_port = args.pru_port
                                        control_port = args.control_port)
    agent.register_task('grip_on', gripper_agent.grip_on)
    agent.register_task('grip_off', gripper_agent.grip_off)
    agent.register_task('grip_brake', gripper_agent.grip_brake)
    agent.register_task('grip_move', gripper_agent.grip_move)
    agent.register_task('grip_home', gripper_agent.grip_home)
    agent.register_task('grip_inp', gripper_agent.grip_inp)
    agent.register_task('grip_alarm', gripper_agent.grip_alarm)
    agent.register_task('grip_reset', gripper_agent.grip_reset)
    agent.register_task('grip_act', gripper_agent.grip_act)
    agent.register_task('grip_mode', gripper_agent.grip_mode)
    agent.register_task('grip_force', gripper_agent.grip_force)

    runner.run(agent, auto_reconnect = True)
