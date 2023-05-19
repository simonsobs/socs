#!/usr/bin/env python3

import argparse
import ctypes
import multiprocessing
import os
import signal
import subprocess
import sys
import time
import numpy as np

import socs.agents.hwp_gripper.drivers.gripper_client as gclient
import socs.agents.hwp_gripper.drivers.GripperBuilder as gb
import socs.agents.hwp_gripper.drivers.GripperCollector as gc

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# from socs.agents.hwp_supervisor.agent import get_op_data


class GripperAgent:
    def __init__(self, agent, mcu_ip, pru_port, control_port,
                 return_port, supervisor_id=None, no_data_timeout=45 * 60):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self._initialized = False
        self.mcu_ip = mcu_ip
        self.pru_port = pru_port
        self.control_port = control_port
        self.return_port = return_port

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        self.collector = None
        self.builder = None
        self.client = None

        self.last_encoder = 0
        self.last_limit = 0
        self.last_limit_time = 0
        self.is_forced = False

        # self.encoder_names = ['Actuator 1 A', 'Actuator 1 B', 'Actuator 2 A',
        #                      'Actuator 2 B', 'Actuator 3 A', 'Actuator 3 B']

        self.encoder_pru = [0, 1, 2, 3, 4, 5]
        self.encoder_edges = multiprocessing.Array(ctypes.c_int, (0, 0, 0, 0, 0, 0))
        self.encoder_edges_record = multiprocessing.Array(ctypes.c_int, (0, 0, 0, 0, 0, 0))
        self.encoder_direction = multiprocessing.Array(ctypes.c_int, (1, 1, 1, 1, 1, 1))

        self.limit_names = ['Actuator 1 Cold', 'Actuator 1 Warm', 'Actuator 2 Cold',
                            'Actuator 2 Warm', 'Actuator 3 Cold', 'Actuator 3 Warm']
        self.limit_pru = [8, 9, 10, 11, 12, 13]
        self.limit_state = [0, 0, 0, 0, 0, 0]

        self.mode = multiprocessing.Value(ctypes.c_bool, False)
        self.force = multiprocessing.Value(ctypes.c_bool, False)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwpgripper', record=True, agg_params=agg_params)
        self.agent.register_feed('gripper_action', record=True)

    @ocs_agent.param('auto_acquire', default=True, type=bool)
    def init_processes(self, session, params):
        if self._initialized:
            self.log.info('Connection already initialized. Returning...')
            return True, 'Connection already initialized'

        self.client = gclient.GripperClient(self.mcu_ip, self.control_port, self.return_port)
        self.collector = gc.GripperCollector(self.pru_port)

        self.agent.start('grip_collect_pru', params=None)
        self.agent.start('grip_build_pru', params=None)
        # self.agent.start('grip_monitor')

        if params['auto_acquire']:
            self.agent.start('grip_acq')

        self._initialized = True
        return True, 'Processes started'

    def grip_on(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_on') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            self.log.info(self._send_command('ON'))

        return True, 'Power on'

    def grip_off(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_off') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            self.log.info(self._send_command('OFF'))

        return True, 'Power off'

    @ocs_agent.param('state', default='ON', type=str)
    @ocs_agent.param('actuator', default=0, type=int, check=lambda x: 0 <= x <= 3)
    def grip_brake(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_brake') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            if params['actuator'] == 0:
                self.log.info(self._send_command('BRAKE ' + params['state']))
            else:
                self.log.info(self._send_command('BRAKE ' + params['state'] + ' ' + str(params['actuator'])))

        return True, 'Changed brake state'

    @ocs_agent.param('mode', default='PUSH', type=str)
    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    @ocs_agent.param('distance', default=0, type=float, check=lambda x: -10. <= x <= 10.)
    def grip_move(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_move') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            pru_chains = [2 * params['actuator'] - 2, 2 * params['actuator'] - 1]
            with self.encoder_direction.get_lock():
                with self.encoder_edges_record.get_lock():
                    for chain in pru_chains:
                        self.encoder_edges_record[chain] = 1
                        if params['distance'] >= 0:
                            self.encoder_direction[chain] = 1
                        elif params['distance'] < 0:
                            self.encoder_direction[chain] = -1

            self.log.info(self._send_command('MOVE ' + params['mode'] + ' ' + str(params['actuator'])
                                             + ' ' + str(params['distance'])))

            with self.encoder_edges_record.get_lock():
                for chain in pru_chains:
                    self.encoder_edges_record[chain] = 0

        return True, 'Moved actuators'

    def grip_home(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_home') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            with self.encoder_edges_record.get_lock():
                for index, _ in enumerate(self.encoder_edges_record):
                    self.encoder_edges_record[index] = 1

            self.log.info(self._send_command('HOME'))

            with self.encoder_edges.get_lock():
                with self.encoder_edges_record.get_lock():
                    for index, _ in enumerate(self.encoder_edges):
                        self.encoder_edges_record[index] = 0
                        self.encoder_edges[index] = 0

        return True, 'Homed actuators'

    def grip_inp(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_inp') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.log.info(self._send_command('INP'))

        return True, 'Queried are actuators in known state'

    def grip_alarm(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_alarm') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.log.info(self._send_command('ALARM'))

        return True, 'Queried alarm state'

    def grip_reset(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_reset') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.log.info(self._send_command('RESET'))

        return True, 'Reset alarm state'

    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    def grip_act(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_act') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            self.log.info(self._send_command('ACT ' + str(params['actuator'])))

        return True, 'Queried actuator connection'

    @ocs_agent.param('value', default=False, type=bool)
    def grip_mode(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_mode') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            with self.mode.get_lock():
                self.mode.value = params['value']

        return True, 'Changed temperature mode'

    @ocs_agent.param('value', default=False, type=bool)
    def grip_force(self, session, params=None):
        with self.lock.acquire_timeout(0, job='grip_force') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if params['value']:
                self.is_forced = False

            with self.force.get_lock():
                self.force.value = params['value']

        return True, 'Changed force parameter'

    def grip_shutdown(self, session, params=None):
        self.log.warn('INITIATING SHUTDOWN')

        with self.lock.acquire_timeout(10, job='grip_shutdown') as acquired:
            if not acquired:
                self.log.error('Could not acquire lock for shutdown')
                return False, 'Could not acquire lock'

            self.shutdown_mode = True

            self.log.info(self._send_command('ON'))
            time.sleep(1)

            self.log.info(self._send_command('BRAKE OFF'))
            time.sleep(1)

            self.log.info(self._send_command('HOME'))
            time.sleep(15)

            for actuator in (1 + np.arange(3) % 3):
                self.log.info(self._send_command('MOVE POS ' + str(actuator) + ' 10'))
                time.sleep(5)

            for actuator in (1 + np.arange(12) % 3):
                self.log.info(self._send_command('MOVE POS ' + str(actuator) + ' 1'))
                time.sleep(3)

                self.log.info(self._send_command('RESET'))
                time.sleep(0.5)

            for actuator in (1 + np.arange(3) % 3):
                self.log.info(self._send_command('MOVE POS ' + str(actuator) + ' -1'))
                time.sleep(3)

            self.log.info(self._send_command('BRAKE ON'))
            time.sleep(1)

            self.log.info(self._send_command('OFF'))
            time.sleep(1)

        return True, 'Shutdown completed'

    def grip_rev_shutdown(self, session, params=None):
        self.shutdown_mode = False
        return True, 'Reversed shutdown mode'

    def grip_acq(self, session, params=None):
        session.set_status('running')

        self._run_acq = True
        while self._run_acq:
            data = {'timestamp': time.time(),
                    'block_name': 'HWPGripper_POS', 'data': {}}

            cur_pos = self._get_pos()
            data['data']['act1_a'] = cur_pos[0]
            data['data']['act1_b'] = cur_pos[1]
            data['data']['act2_a'] = cur_pos[2]
            data['data']['act2_b'] = cur_pos[3]
            data['data']['act3_a'] = cur_pos[4]
            data['data']['act3_b'] = cur_pos[5]

            self.agent.publish_to_feed('hwpgripper', data)

            session.data = {'act1_a': cur_pos[0],
                            'act1_b': cur_pos[1],
                            'act2_a': cur_pos[2],
                            'act2_b': cur_pos[3],
                            'act3_a': cur_pos[4],
                            'act3_b': cur_pos[5],
                            'last_updated': time.time()}

            time.sleep(1)

        self.agent.feeds['hwpgripper'].flush_buffer()
        session.set_status('stopping')
        return True, 'Aquisition exited cleanly'

    def grip_monitor(self, session, params=None):
        session.set_status('running')
        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, 'No supervisor ID set'

        self._run_monitor = True
        while self._run_monitor:
            res = get_op_data(self.supervisor_id)
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['gripper']

            if action == 'ok':
                last_ok_time = time.time()

            elif action == 'no_data':
                if (time.time() - last_ok_time) > self.no_data_timeout:
                    if not self.shutdown_mode:
                        self.agent.start('grip_shutdown')

            elif action == 'stop':
                if not self.shutdown_mode:
                    self.agent.start('grip_shutdown')

            data = {
                'data': {'gripper_action': action},
                'block_name': 'gripper_action',
                'timestamp': time.time()
            }

            self.agent.publish_to_feed('gripper_action', data)
            session.data = {
                'gripper_action': action,
                'time': time.time()
            }

            time.sleep(0.2)

        session.set_status('stopping')
        return True, 'Gripper monitor exited cleanly'

    def grip_collect_pru(self, session, params=None):
        session.set_status('running')

        if self.collector is None:
            return False, 'Pru collector not defined'

        self._run_collect_pru = True
        while self._run_collect_pru:
            self.collector.relay_gripper_data()

        session.set_status('stopping')
        return True, 'Pru collection exited cleanly'

    def grip_build_pru(self, session, params=None):
        session.set_status('running')

        if self.collector is None:
            return False, 'Pru collector not defined'

        self.builder = gb.GripperBuilder(self.collector)

        if self.client is None:
            return False, 'Control client not defined'

        with self.lock.acquire_timeout(10, job='grip_limit_switches') as acquired:
            self._send_command('EMG ON')

        self._run_build_pru = True
        while self._run_build_pru:
            encoder_data = self.builder.process_packets()
            if len(encoder_data['state']):
                edges = np.concatenate(([self.last_encoder ^ encoder_data['state'][0]],
                                        encoder_data['state'][1:] ^ encoder_data['state'][:-1]))

                with self.encoder_edges.get_lock():
                    with self.encoder_direction.get_lock():
                        with self.encoder_edges_record.get_lock():
                            for index, pru in enumerate(self.encoder_pru):
                                if self.encoder_edges_record[index]:
                                    self.encoder_edges[index] += \
                                        self.encoder_direction[index] * np.sum((edges >> pru) & 1)

                self.last_encoder = encoder_data['state'][-1]

            clock, state = self.builder.limit_state[0], int(self.builder.limit_state[1])

            for index, pru in enumerate(self.limit_pru):
                self.limit_state[index] = ((state & (1 << pru)) >> pru)

            if (state and not self.mode.value) or self.limit_state[0] or self.limit_state[2] or self.limit_state[4]:
                self.last_limit_time = time.time()
                if self.force.value and not self.is_forced:
                    with self.lock.acquire_timeout(10, job='grip_limit_switches') as acquired:
                        self._send_command('EMG ON')
                        self.is_forced = True
                elif self.last_limit != state and not self.force.value:
                    with self.lock.acquire_timeout(10, job='grip_limit_switches') as acquired:
                        self.last_limit = state

                        if (self.limit_state[1] and not self.mode.value) or self.limit_state[0]:
                            self._send_command('EMG OFF 1')
                        else:
                            self._send_command('EMG ON 1')

                        if (self.limit_state[3] and not self.mode.value) or self.limit_state[2]:
                            self._send_command('EMG OFF 2')
                        else:
                            self._send_command('EMG ON 2')

                        if (self.limit_state[5] and not self.mode.value) or self.limit_state[4]:
                            self._send_command('EMG OFF 3')
                        else:
                            self._send_command('EMG ON 3')

                        print('Limit switch activation at clock: {}'.format(clock))
                        for index, name in enumerate(self.limit_names):
                            if self.limit_state[index]:
                                print('{} activated'.format(name))
            else:
                if time.time() - self.last_limit_time > 5:
                    if self.last_limit != 0:
                        with self.lock.acquire_timeout(10, job='grip_limit_switches') as acquired:
                            self._send_command('EMG ON')
                            self.last_limit = 0

        session.set_status('stopping')
        return True, 'Pru building exited cleanly'

    def _stop_acq(self, session, params=None):
        if self._run_acq:
            self._run_acq = False
        return True, 'Stopping gripper acquisition'

    def _stop_monitor(self, session, params=None):
        if self._run_monitor:
            self._run_monitor = False
        return True, 'Stopping monitor'

    def _stop_collect_pru(self, session, params=None):
        if self._run_collect_pru:
            self._run_collect_pru = False
        return True, 'Stopping collecting pru packets'

    def _stop_build_pru(self, session, params=None):
        if self._run_build_pru:
            self._run_build_pru = False
        return True, 'Stopping pru packet building'

    def _send_command(self, command):
        if self.client is None:
            return False

        _ = self.client.listen()
        self.client.send_data(command)
        return self.client.listen(timeout=10)

    def _get_pos(self):
        slope = 1 / 160.
        return [rising_edges * slope for rising_edges in self.encoder_edges]

    def _wait_for_responce(self, timeout=10):
        start = time.time()
        while time.time() - start < timeout:
            if self.command_responce.value == 3:
                pass
            else:
                return self.command_responce.value
            time.sleep(0.1)

        return self.command_responce.value


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--mcu_ip', type=str,
                        help='IP of Gripper Beaglebone')
    pgroup.add_argument('--pru_port', type=int, default=8040,
                        help='Arbitrary port for actuator encoders')
    pgroup.add_argument('--control_port', type=int, default=8041,
                        help='Arbitrary port for actuator control')
    pgroup.add_argument('--return_port', type=int, default=8042,
                        help='Arbitrary port for actuator messaging')
    pgroup.add_argument('--supervisor-id', type=str,
                        help='Instance ID for HWP Supervisor agent')
    pgroup.add_argument('--no-data-timeout', type=float, default=45 * 60,
                        help="Time (sec) after which a 'no_data' action should "
                        "trigger a shutdown")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPGripperAgent',
                                  parser=parser,
                                  args=args)

    init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    gripper_agent = GripperAgent(agent, mcu_ip=args.mcu_ip,
                                 pru_port=args.pru_port,
                                 control_port=args.control_port,
                                 return_port=args.return_port,
                                 supervisor_id=args.supervisor_id,
                                 no_data_timeout=args.no_data_timeout)
    agent.register_process('grip_acq', gripper_agent.grip_acq,
                           gripper_agent._stop_acq)
    agent.register_process('grip_monitor', gripper_agent.grip_monitor,
                           gripper_agent._stop_monitor)
    agent.register_process('grip_collect_pru', gripper_agent.grip_collect_pru,
                           gripper_agent._stop_collect_pru)
    agent.register_process('grip_build_pru', gripper_agent.grip_build_pru,
                           gripper_agent._stop_build_pru)
    agent.register_task('init_processes', gripper_agent.init_processes,
                        startup=init_params)
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
    agent.register_task('grip_shutdown', gripper_agent.grip_shutdown)
    agent.register_task('grip_rev_shutdown', gripper_agent.grip_rev_shutdown)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()