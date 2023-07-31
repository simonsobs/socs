#!/usr/bin/env python3

import argparse
import ctypes
import multiprocessing
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from typing import Optional

import socs.agents.hwp_gripper.drivers.gripper_client as cli
from socs.agents.hwp_supervisor.agent import get_op_data


class GripperAgent:
    """
    Agent for controlling/monitoring the HWP's three LEY32C-30 linear actuators.
    This interfaces with the GripperServer running on the beaglebone
    microcontroller (https://github.com/simonsobs/sobonelib/blob/main/hwp_gripper/control/gripper_server.py).

    This agent will issue commands to the microcontroller via OCS, and publish
    gripper position and limit switch states to grafana.

    Args:
        mcu_ip (string):
            IP of the Beaglebone microcontroller running adjacent code
        control_port (int):
            Port for control commands sent to the Beaglebone.
        supervisor_id (str):
            ID of HWP supervisor
        no_data_timeout (float):
            Time (in seconds) to wait between receiving 'no_data' actions from
            the supervisor and triggering a shutdown
    """
    def __init__(self, agent, mcu_ip, control_port, supervisor_id=None,
                 no_data_timeout=30 * 60):
        self.agent = agent
        self.log = agent.log
        self.client_lock = TimeoutLock()

        self._initialized = False
        self.mcu_ip = mcu_ip
        self.control_port = control_port

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        self._gripper_state = None

        self.client : Optional[cli.GripperClient] = None

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwp_gripper', record=True, agg_params=agg_params)
        self.agent.register_feed('gripper_action', record=True)
    
    def _run_client_func(self, func, *args, lock_timeout=2, 
                         job=None, check_shutdown=True, **kwargs):
        if self.shutdown_mode and check_shutdown:
            raise RuntimeError(
                'Cannot run client function, shutdown mode is in effect'
            )

        lock_kw = {'timeout': lock_timeout}
        if job is not None:
            lock_kw['job'] = job
        with self.client_lock.acquire_timeout(**lock_kw) as acquired:
            if not acquired:
                self.log.error(
                    f"Could not acquire lock! Job {self.client_lock.job} is "
                     "already running."
                )
                raise TimeoutError('Could not acquire lock')
            
            return_dict = func(*args, **kwargs)

        for line in return_dict['log']:
            self.log.info(line)

        return return_dict
    
    def _get_hwp_freq(self):
        if self.supervisor_id is None:
            raise ValueError("No Supervisor ID set")
        
        res = get_op_data(self.supervisor_id, 'monitor')
        return res['data']['hwp_state']['pid_current_freq']

    @ocs_agent.param('auto_acquire', default=True, type=bool)
    def init_connection(self, session, params):
        """init_connection(auto_acquire=False)

        **Task** - Initialize connection to the GripperServer on the BeagleBone
        micro-controller

        Parameters:
            auto_acquire (bool, optional): Default is True. Starts data acquisition
                after initialization if True
        """
        if self._initialized:
            self.log.info('Connection already initialized. Returning...')
            return True, 'Connection already initialized'

        self.client = cli.GripperClient(self.mcu_ip, self.control_port)

        self.agent.start('monitor')

        if params['auto_acquire']:
            self.agent.start('acq')

        self._initialized = True
        return True, 'Processes started'

    @ocs_agent.param('state', default=True, type=bool)
    def power(self, session, params=None):
        """power(state=True)

        **Task** - If turning on, will power on the linear and disengage brakes.
        If turning off, will cut power to the linear actuators and engage
        brakes.

        Parameters:
            state (bool): State to set the actuator power to. Takes bool input
        """
        return_dict = self._run_client_func(
            self.client.power, params['state'], job='power'
        )
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('state', default=True, type=bool)
    @ocs_agent.param('actuator', default=0, type=int, check=lambda x: 0 <= x <= 3)
    def brake(self, session, params=None):
        """brake(state=True, actuator=0)

        **Task** - Controls actuator brakes

        Parameters:
            state (bool):
                State to set the actuator brake to. Takes bool input
            actuator (int):
                Actuator number. Takes input of 0-3 with 1-3 controlling and
                individual actuator and 0 controlling all three
        """
        return_dict = self._run_client_func(
            self.client.brake, params['state'], params['actuator'], job='brake'
        )
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('mode', default='push', type=str, choices=['push', 'pos'])
    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    @ocs_agent.param('distance', default=0, type=float, check=lambda x: -10. <= x <= 10.)
    def move(self, session, params=None):
        """move(mode='pos', actuator=1, distance=1.3)

        **Task** - Move an actuator a specific distance

        Parameters:
            mode (str):
                Movement mode. Takes inputs of 'pos' (positioning) or 'push'
                (pushing)
            actuator (int):
                Actuator number 1-3
            distance (float):
                Distance to move (mm). Takes positive and negative numbers for
                'pos' mode. Takes only positive numbers for 'push' mode. Value
                should be a multiple of 0.1.

        Notes:
            Positioning mode is used when you want to position the actuators without
            gripping the rotor. Pushing mode is used when you want the grip the
            rotor.
        """
        return_dict = self._run_client_func(
            self.client.move, params['mode'], params['actuator'],
            params['distance'], job='move'
        )
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def home(self, session, params=None):
        """home()
        **Task** - Homes and recalibrates the position of the actuators

        Note:
            This action much be done first after a power cycle. Otherwise the
            controller will throw an error.
        """
        return_dict = self._run_client_func(self.client.home, job='home')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def inp(self, session, params=None):
        """inp()

        **Task** - Queries whether the actuators are in a known position. This
        tells you whether the windows software has detected that the actuator
        has been homed.
        """
        return_dict = self._run_client_func(
            self.client.inp, job='INP', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def alarm(self, session, params=None):
        """alarm()

        **Task** - Queries the actuator controller alarm state
        """
        return_dict = self._run_client_func(
            self.client.alarm, job='alarm', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def reset(self, session, params=None):
        """reset()
        **Task** - Resets the current active controller alarm
        """
        return_dict = self._run_client_func(self.client.reset, job='reset')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    def act(self, session, params=None):
        """act(actuator=1)

        **Task** - Queries whether an actuator is connected

        Parameters:
            actuator (int): Actuator number 1-3
        """
        return_dict = self._run_client_func(
            self.client.act, params['actuator'], job='act', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('value', type=bool)
    def is_cold(self, session, params=None):
        """is_cold(value=False)

        **Task** - Set the code to operate in warm/cold grip configuration

        Parameters:
            value (bool): Set to warm grip (False) or cold grip (True)

        Notes:
            Configures the software to query the correct set of limit switches. The
            maximum extension of the actuators depends on the cryostat temperature.
        """
        return_dict = self._run_client_func(
            self.client.is_cold, params['value'], job='is_cold')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('value', default=False, type=bool)
    def force(self, session, params=None):
        """force(value=False)

        **Task** - Set the code to ignore limit switch information

        Parameters:
            value (bool): Use limit switch information (False) or ignore limit
                switch information (True)

        Notes:
            By default the code is configured to prevent actuator movement if
            on of the limit switches has been triggered. This function can be
            called to forcibly move the actuators even with a limit switch
            trigger.
        """
        return_dict = self._run_client_func(
            self.client.force, params['value'], job='force')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"
    
    def shutdown(self, session, params=None):
        """shutdown()
        **Task** - Series of commands executed during a shutdown.
        This will return grippers to their home position, then move them each
        inwards incrementally.

        Notes:
            This function is called once a shutdown trigger has been given.
        """

        # First check if the HWP is actually stopped
        hwp_freq = self._get_hwp_freq()
        if hwp_freq > 0.05:
            raise RuntimeError("HWP is not stopped! Not performing shutdown")
        
        self.shutdown_mode = True

        self.log.warn('INITIATING SHUTDOWN')
        with self.lock.acquire_timeout(10, job='shutdown') as acquired:
            if not acquired:
                self.log.error('Could not acquire lock for shutdown')
                return False, 'Could not acquire lock'

            self.shutdown_mode = True

            time.sleep(5 * 60)

            self.log.info(self.client.power(True))
            time.sleep(1)

            self.log.info(self.client.brake(False))
            time.sleep(1)

            self.log.info(self.client.home())
            time.sleep(15)

            for actuator in [1, 2, 3]:
                self.log.info(self.client.move('POS', actuator, 10))
                time.sleep(5)

            for _ in range(4):
                for actuator in [1, 2, 3]:
                    self.log.info(self.client.move('POS', actuator, 1))
                    time.sleep(3)

                    self.log.info(self.client.reset())
                    time.sleep(0.5)

            for actuator in [1, 2, 3]:
                self.log.info(self.client.move('POS', actuator, -1))
                time.sleep(3)

            self.log.info(self.client.brake(True))
            time.sleep(1)

            self.log.info(self.client.power(False))
            time.sleep(1)

        return True, 'Shutdown completed'

    def cancel_shutdown(self, session, params=None):
        """cancel_shutdown()
        **Task** - Take the gripper agent out of shutdown mode
        """
        self.shutdown_mode = False
        return True, 'Cancelled shutdown mode'
    
    def monitor_state(self, session, params=None):
        """monitor_state()

        **Process** - Process to monitor the gripper state
        """
        session.set_status('running')
        sleep_time = 5

        while session.status in ['starting', 'running']:
            return_dict = self._run_client_func(
                self.client.get_state, job='get_state', check_shutdown=False
            )
            now = time.time()

            # Dict of the 'GripperState' class from the pru_monitor
            state = return_dict['result']
            data = {
                'last_packet_received': state['last_packet_received']
            }
            for act in state['actuators']:
                axis = act['axis']
                data.update({
                    f'act{axis}_pos': act['pos'],
                    f'act{axis}_calibrated': act['calibrated'],
                    f'act{axis}_limit_cold_grip_state': act['limits']['cold_grip']['state'],
                    f'act{axis}_limit_warm_grip_state': act['limits']['warm_grip']['state'],
                })
            
            session.data = {
                'state': data,
                'last_updated': now,
            }
            _data = {
                'block_name': 'gripper_state',
                'timestamp': now,
                'data': data,
            }
            self.agent.publish_to_feed('hwp_gripper', _data)
            time.sleep(sleep_time)

    def _stop_monitor_state(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting monitor_state process to stop"

    def _stop_monitor_supervisor(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting monitor_supervisor process to stop"

    def monitor_supervisor(self, session, params=None):
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

    def _stop_monitor_supervisor(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting monitor_supervisor process to stop"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--mcu_ip', type=str,
                        help='IP of Gripper Beaglebone')
    pgroup.add_argument('--control_port', type=int, default=8041,
                        help='Arbitrary port for actuator control')
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
                                 supervisor_id=args.supervisor_id,
                                 no_data_timeout=args.no_data_timeout)
    agent.register_process('acq', gripper_agent.acq,
                           gripper_agent._stop_acq)
    agent.register_process('monitor_state', gripper_agent.monitor_state,
                           gripper_agent._stop_monitor_state)
    agent.register_process('monitor_supervisor', gripper_agent.monitor_state,
                           gripper_agent._stop_monitor_supervisor)
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
    agent.register_task('cancel_shutdown', gripper_agent.cancel_shutdown)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
