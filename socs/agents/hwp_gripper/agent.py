#!/usr/bin/env python3

import argparse
import ctypes
import multiprocessing
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

import socs.agents.hwp_gripper.drivers.gripper_client as cli
import socs.agents.hwp_gripper.drivers.gripper_collector as col
from socs.agents.hwp_supervisor.agent import get_op_data


class GripperAgent:
    """Agent for controlling/monitoring the HWP's three LEY32C-30 linear actuators.
    Functions include issuing movement commands, monitoring actuator positions, and
    handling limit switch activation

    Args:
        mcu_ip (string): IP of the Beaglebone mircocontroller running adjacent code
        pru_port (int): Port for pru packet communication arbitrary* but needs to be
            changed in beaglebone code as well
        control_port (int): Port for control commands sent to the Beaglebone. Arbitrary
        supervisor_id (str): ID of HWP supervisor
        no_data_timeout (float): Time (in seconds) to wait between receiving
            'no_data' actions from the supervisor and triggering a shutdown
        limit_pos (arr, float): Expected physical position of the limit switches in mm.
            [Actuator 1 Cold, Actuator 1 Warm, Actuator 2, Cold, Actuator 2 Warm,
             Actuator 3 Cold, Actuator 3 Warm]
    """

    def __init__(self, agent, mcu_ip, pru_port, control_port,
                 supervisor_id=None, no_data_timeout=30 * 60,
                 limit_pos=[13., 10., 13., 10., 13., 10.]):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self._initialized = False
        self.mcu_ip = mcu_ip
        self.pru_port = pru_port
        self.control_port = control_port

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        self.collector = None
        self.client = None

        self.last_encoder = 0
        self.last_limit = 0
        self.last_limit_time = 0
        self.limit_pos = limit_pos
        self.is_forced = False

        # The Beaglebone code periodically queries the status of six pins measuring the
        # encoder signal and sends that data to the agent in the form of UDP packets.
        # Each actuator has two encoder signals

        # Similarly the Beaglebone code also periodically queries the status of six pins
        # hooked up to the warm and cold limit switches on each actuator and sends that
        # data to the agent as seperate UDP packets

        # Names of the encoder chains (currently the code does not use these, but it's still a
        # good reference to know which index corresponds to which chain)
        # self.encoder_names = ['Actuator 1 A', 'Actuator 1 B', 'Actuator 2 A',
        #                      'Actuator 2 B', 'Actuator 3 A', 'Actuator 3 B']

        # Which bits on Beaglebone PRU1 register are used for the encoder (these values shouldn't change)
        self.encoder_pru = [0, 1, 2, 3, 4, 5]

        # Array which holds how many rising/falling edges have been detected from the encoder signal
        self.encoder_edges = multiprocessing.Array(ctypes.c_int, (0, 0, 0, 0, 0, 0))

        # Array which tells the code whether it should use incomming data to change the number of
        # encoder edges. There are six values, one for each encoder chain
        self.encoder_edges_record = multiprocessing.Array(ctypes.c_int, (0, 0, 0, 0, 0, 0))

        # Array which tells the code what direction the actuator should be moving in. There are six
        # values, one for each encoder chain
        self.encoder_direction = multiprocessing.Array(ctypes.c_int, (1, 1, 1, 1, 1, 1))

        # Names of the limit chains
        self.limit_names = ['Actuator 1 Cold', 'Actuator 1 Warm', 'Actuator 2 Cold',
                            'Actuator 2 Warm', 'Actuator 3 Cold', 'Actuator 3 Warm']

        # Which bits on Beaglebone PRU0 register are used for the limit switches (these values shouldn't
        # change)
        self.limit_pru = [8, 9, 10, 11, 12, 13]

        # Array which holds the current status of each limit switch
        self.limit_state = [0, 0, 0, 0, 0, 0]

        # Variable to tell the code whether the cryostat is warm (False) or cold (True). Needs to be
        # given by the user
        self.is_cold = multiprocessing.Value(ctypes.c_bool, False)

        # Variable to tell the code whether it should ignore any flags sent by the limit switches. If
        # this variable is False the actuators will only move while none of the active limit switches
        # are triggered (which limit switches are chosen depends on self.is_cold)
        self.force = multiprocessing.Value(ctypes.c_bool, False)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwpgripper', record=True, agg_params=agg_params)
        self.agent.register_feed('gripper_action', record=True)

    @ocs_agent.param('auto_acquire', default=True, type=bool)
    def init_connection(self, session, params):
        """init_connection(auto_acquire=False)
        **Task** - Initialize connection to the Beaglebone microcontroller

        Parameters:
            auto_acquire (bool, optional): Default is True. Starts data acquisition
                after initialization if True
        """
        if self._initialized:
            self.log.info('Connection already initialized. Returning...')
            return True, 'Connection already initialized'

        self.client = cli.GripperClient(self.mcu_ip, self.control_port)
        self.collector = col.GripperCollector(self.pru_port)

        self.agent.start('collect_pru', params=None)
        self.agent.start('monitor')

        if params['auto_acquire']:
            self.agent.start('acq')

        self._initialized = True
        return True, 'Processes started'

    @ocs_agent.param('state', default=True, type=bool)
    def power(self, session, params=None):
        """power(state = True)
        **Task** - Turns on/off power to the linear actuators. If brakes are on/off, turn them off/on

        Parameters:
            state (bool): State to set the actuator power to. Takes bool input
        """
        with self.lock.acquire_timeout(0, job='power') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            return_dict = self.client.POWER(params['state'])
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('state', default=True, type=bool)
    @ocs_agent.param('actuator', default=0, type=int, check=lambda x: 0 <= x <= 3)
    def brake(self, session, params=None):
        """brake(state = True, actuator = 0)
        **Task** - Controls actuator brakes

        Parameters:
            state (bool): State to set the actuator brake to. Takes bool input
            actuator (int): Actuator number. Takes input of 0-3 with 1-3 controlling
                and individual actuator and 0 controlling all three
        """
        with self.lock.acquire_timeout(0, job='brake') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            return_dict = self.client.BRAKE(params['state'], params['actuator'])
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('mode', default='push', type=str, choices=['push', 'pos'])
    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    @ocs_agent.param('distance', default=0, type=float, check=lambda x: -10. <= x <= 10.)
    def move(self, session, params=None):
        """move(mode = 'pos', actuator = 1, distance = 1.3)
        **Task** - Move an actuator a specific distance

        Parameters:
            mode (str): Movement mode. Takes inputs of 'pos' (positioning) or
                'push' (pushing)
            actuator (int): Actuator number 1-3
            distance (float): Distance to move. Takes positive and negative numbers
                for 'pos' mode. Takes only positive numbers for 'push' mode. Value
                should be a multiple of 0.1

        Notes:
            Positioning mode is used when you want to position the actuators without
            gripping the rotor. Pushing mode is used when you want the grip the
            rotor.
        """
        with self.lock.acquire_timeout(0, job='move') as acquired:
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

            cur_pos = self._get_pos()[2 * params['actuator'] - 2]
            warm_limit_pos = self.limit_pos[2 * params['actuator'] - 1]
            cold_limit_pos = self.limit_pos[2 * params['actuator'] - 2]
            if cur_pos + params['distance'] > warm_limit_pos and not self.force and not self.is_cold:
                self.log.warn('Move command beyond warm limit switch position')
                dist = (warm_limit_pos - cur_pos) - (warm_limit_pos - cur_pos) % 0.1
                if dist < 0:
                    self.log.error('Actuator already beyond warm limit switch position')
                    dist = 0
            elif cur_pos + params['distance'] > cold_limit_pos and not self.force:
                self.log.warn('Move command beyond cold limit switch position')
                dist = (cold_limit_pos - cur_pos) - (cold_limit_pos - cur_pos) % 0.1
                if dist < 0:
                    self.log.error('Actuator already beyond cold limit switch position')
                    dist = 0
            else:
                dist = params['distance']

            return_dict = self.client.MOVE(params['mode'], params['actuator'], dist)
            [self.log.info(line) for line in return_dict['log']]

            with self.encoder_edges_record.get_lock():
                for chain in pru_chains:
                    self.encoder_edges_record[chain] = 0

            return return_dict['result'], f"Success: {return_dict['result']}"

    def home(self, session, params=None):
        """home()
        **Task** - Homes and recalibrates the position of the actuators

        Note:
            This action much be done first after a power cycle. Otherwise the
            controller will throw an error.
        """
        with self.lock.acquire_timeout(0, job='home') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if self.shutdown_mode:
                return False, 'Shutdown mode is in effect'

            with self.encoder_edges_record.get_lock():
                for index, _ in enumerate(self.encoder_edges_record):
                    self.encoder_edges_record[index] = 1

            return_dict = self.client.HOME()
            [self.log.info(line) for line in return_dict['log']]

            with self.encoder_edges.get_lock():
                with self.encoder_edges_record.get_lock():
                    for index, _ in enumerate(self.encoder_edges):
                        self.encoder_edges_record[index] = 0
                        self.encoder_edges[index] = 0

            return return_dict['result'], f"Success: {return_dict['result']}"

    def inp(self, session, params=None):
        """inp()
        **Task** - Queries whether the actuators are in a known position
        """
        with self.lock.acquire_timeout(0, job='inp') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return_dict = self.client.INP()
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    def alarm(self, session, params=None):
        """alarm()
        **Task** - Queries the actuator controller alarm state
        """
        with self.lock.acquire_timeout(0, job='alarm') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return_dict = self.client.ALARM()
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    def reset(self, session, params=None):
        """reset()
        **Task** - Resets the current active controller alarm
        """
        with self.lock.acquire_timeout(0, job='reset') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return_dict = self.client.RESET()
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    def act(self, session, params=None):
        """act(actuator = 1)
        **Task** - Queries whether an actuator is connected

        Parameters:
            actuator (int): Actuator number 1-3
        """
        with self.lock.acquire_timeout(0, job='act') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            return_dict = self.client.ACT(params['actuator'])
            [self.log.info(line) for line in return_dict['log']]

            return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('value', default=False, type=bool)
    def is_cold(self, session, params=None):
        """is_cold(value = False)
        **Task** - Set the code to operate in warm/cold grip configuration

        Parameters:
            value (bool): Set to warm grip (False) or cold grip (True)

        Notes:
            Configures the software to query the correct set of limit switches. The
            maximum extension of the actuators depends on the cryostat temperature.
        """
        with self.lock.acquire_timeout(0, job='is_cold') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            with self.is_cold.get_lock():
                self.is_cold.value = params['value']

        return True, 'Changed temperature mode'

    @ocs_agent.param('value', default=False, type=bool)
    def force(self, session, params=None):
        """force(value = False)
        **Tast** - Set the code to ignore limit switch information

        Parameters:
            value (bool): Use limit switch information (False) or ignore limit
                switch information (True)

        Notes:
            By default the code is configured to prevent actuator movement if
            on of the limit switches has been triggered. This function can be
            called to forcibly move the actuators even with a limit switch
            trigger.
        """
        with self.lock.acquire_timeout(0, job='force') as acquired:
            if not acquired:
                self.log.warn('Could not perform action because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            if params['value']:
                self.is_forced = False

            with self.force.get_lock():
                self.force.value = params['value']

        return True, 'Changed force parameter'

    def shutdown(self, session, params=None):
        """shutdown()
        **Task** - Series of commands executed during a shutdown

        Notes:
            This function is called once a shutdown trigger has been given.
        """
        self.log.warn('INITIATING SHUTDOWN')

        with self.lock.acquire_timeout(10, job='shutdown') as acquired:
            if not acquired:
                self.log.error('Could not acquire lock for shutdown')
                return False, 'Could not acquire lock'

            self.shutdown_mode = True

            time.sleep(5 * 60)

            self.log.info(self.client.POWER(True))
            time.sleep(1)

            self.log.info(self.client.BRAKE(False))
            time.sleep(1)

            self.log.info(self.client.HOME())
            time.sleep(15)

            for actuator in (1 + np.arange(3) % 3):
                self.log.info(self.client.MOVE('POS', actuator, 10))
                time.sleep(5)

            for actuator in (1 + np.arange(12) % 3):
                self.log.info(self.client.MOVE('POS', actuator, 1))
                time.sleep(3)

                self.log.info(self.client.RESET())
                time.sleep(0.5)

            for actuator in (1 + np.arange(3) % 3):
                self.log.info(self.client.MOVE('POS', actuator, -1))
                time.sleep(3)

            self.log.info(self.client.BRAKE(True))
            time.sleep(1)

            self.log.info(self.client.POWER(False))
            time.sleep(1)

        return True, 'Shutdown completed'

    def rev_shutdown(self, session, params=None):
        """rev_shutdown()
        **Task** - Take the gripper agent out of shutdown mode
        """
        self.shutdown_mode = False
        return True, 'Reversed shutdown mode'

    def acq(self, session, params=None):
        """acq()
        **Process** - Publishes gripper positions

        Notes:
            The most recent data collected  is stored in session data in the
            structure::

                >>> responce.session['data']
                {'act1_a': 0,
                 'act1_b': 0,
                 'act2_a': 0,
                 'act2_b': 0,
                 'act3_a': 0,
                 'act3_b': 0,
                 'last_updated': 1649085992.719602}
        """
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

    def monitor(self, session, params=None):
        """monitor()
        **Process** - Monitor the shutdown of the agent
        """
        session.set_status('running')
        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, 'No supervisor ID set'

        self._inital_warning = True
        self._run_monitor = True
        while self._run_monitor:
            res = get_op_data(self.supervisor_id, 'monitor')
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['gripper']

            if action == 'ok':
                last_ok_time = time.time()

            elif action == 'no_data':
                if (time.time() - last_ok_time) > self.no_data_timeout:
                    if not self.shutdown_mode:
                        self.agent.start('shutdown')

            elif action == 'stop':
                if not self.shutdown_mode:
                    cur_freq = res['data']['hwp_state']['pid_current_freq']
                    if cur_freq is None and self._initial_warning:
                        self._initial_warning = False
                        self.log.error("Missing pid frequency data")
                    elif cur_freq < 0.05:
                        self._initial_warning = True
                        self.agent.start('shutdown')

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

    def collect_pru(self, session, params=None):
        """collect_pru()
        **Process** - Collects and extracts data from raw encoder data; updates
            changes to the gripper positions and handles any triggered limit switches
        """
        session.set_status('running')

        if self.collector is None:
            return False, 'Pru collector not defined'

        if self.client is None:
            return False, 'Control client not defined'

        with self.lock.acquire_timeout(10, job='collect_pru'):
            self.client.EMG(True)

        self._run_collect_pru = True
        while self._run_collect_pru:
            # collect data packets
            self.collector.relay_gripper_data()

            # Use collected data packets to find changes in gripper positions
            encoder_data = self.collector.process_packets()
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

            # Check if any of the limit switches have been triggered and prevent gripper movement if necessary
            clock, state = self.collector.limit_state[0], int(self.collector.limit_state[1])

            for index, pru in enumerate(self.limit_pru):
                self.limit_state[index] = ((state & (1 << pru)) >> pru)

            if (state and not self.is_cold.value) or self.limit_state[0] or self.limit_state[2] \
                    or self.limit_state[4]:
                self.last_limit_time = time.time()
                if self.force.value and not self.is_forced:
                    with self.lock.acquire_timeout(10, job='collect_pru'):
                        self.client.EMG(True)
                        self.is_forced = True
                elif self.last_limit != state and not self.force.value:
                    with self.lock.acquire_timeout(10, job='collect_pru'):
                        self.last_limit = state

                        if (self.limit_state[1] and not self.is_cold.value) or self.limit_state[0]:
                            self.client.EMG(False, 1)
                        else:
                            self.client.EMG(True, 1)

                        if (self.limit_state[3] and not self.is_cold.value) or self.limit_state[2]:
                            self.client.EMG(False, 2)
                        else:
                            self.client.EMG(True, 2)

                        if (self.limit_state[5] and not self.is_cold.value) or self.limit_state[4]:
                            self.client.EMG(False, 3)
                        else:
                            self.client.EMG(True, 3)

                        print('Limit switch activation at clock: {}'.format(clock))
                        for index, name in enumerate(self.limit_names):
                            if self.limit_state[index]:
                                print('{} activated'.format(name))
            else:
                if time.time() - self.last_limit_time > 5:
                    if self.last_limit != 0:
                        with self.lock.acquire_timeout(10, job='collect_pru'):
                            self.client.EMG(True)
                            self.last_limit = 0

        session.set_status('stopping')
        return True, 'Pru collecting exited cleanly'

    def _stop_acq(self, session, params=None):
        """
        Stop acq process
        """
        if self._run_acq:
            self._run_acq = False
        return True, 'Stopping gripper acquisition'

    def _stop_monitor(self, session, params=None):
        """
        Stop monitor process
        """
        if self._run_monitor:
            self._run_monitor = False
        return True, 'Stopping monitor'

    def _stop_collect_pru(self, session, params=None):
        """
        Stop collect_pru process
        """
        if self._run_collect_pru:
            self._run_collect_pru = False
        return True, 'Stopping collecting pru packets'

    def _get_pos(self):
        """
        Converts raw encoder rising edges to millimeters
        """
        slope = 1 / 160.
        return [rising_edges * slope for rising_edges in self.encoder_edges]


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
    pgroup.add_argument('--supervisor-id', type=str,
                        help='Instance ID for HWP Supervisor agent')
    pgroup.add_argument('--no-data-timeout', type=float, default=45 * 60,
                        help="Time (sec) after which a 'no_data' action should "
                        "trigger a shutdown")
    pgroup.add_argument('--limit_pos', help="Physical position of limit switches (mm)")
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
                                 supervisor_id=args.supervisor_id,
                                 no_data_timeout=args.no_data_timeout)
    agent.register_process('acq', gripper_agent.acq,
                           gripper_agent._stop_acq)
    agent.register_process('monitor', gripper_agent.monitor,
                           gripper_agent._stop_monitor)
    agent.register_process('collect_pru', gripper_agent.collect_pru,
                           gripper_agent._stop_collect_pru)
    agent.register_task('init_connection', gripper_agent.init_connection,
                        startup=init_params)
    agent.register_task('power', gripper_agent.power)
    agent.register_task('brake', gripper_agent.brake)
    agent.register_task('move', gripper_agent.move)
    agent.register_task('home', gripper_agent.home)
    agent.register_task('inp', gripper_agent.inp)
    agent.register_task('alarm', gripper_agent.alarm)
    agent.register_task('reset', gripper_agent.reset)
    agent.register_task('act', gripper_agent.act)
    agent.register_task('is_cold', gripper_agent.is_cold)
    agent.register_task('force', gripper_agent.force)
    agent.register_task('shutdown', gripper_agent.shutdown)
    agent.register_task('rev_shutdown', gripper_agent.rev_shutdown)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
