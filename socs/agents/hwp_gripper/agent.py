import argparse
import time
from typing import Optional

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

import socs.agents.hwp_gripper.drivers.gripper_client as cli
from socs.agents.hwp_supervisor.agent import get_op_data


class HWPGripperAgent:
    """
    Agent for controlling/monitoring the HWP's three LEY32C-30 linear actuators.
    This interfaces with the GripperServer running on the beaglebone
    microcontroller (https://github.com/simonsobs/sobonelib/blob/main/hwp_gripper/control/gripper_server.py).

    This agent will issue commands to the microcontroller via OCS, and publish
    gripper position and limit switch states to grafana.

    Args:
        agent (ocs.ocs_agent.OCSAgent):
            Agent instance
        args (argparse.Namespace):
            Parsed command line arguments namespace.
    """

    def __init__(self, agent, args):
        self.agent = agent
        self.log = agent.log
        self.client_lock = TimeoutLock()

        self._initialized = False
        self.mcu_ip = args.mcu_ip
        self.control_port = args.control_port
        self.warm_grip_distance = args.warm_grip_distance
        self.adjustment_distance = args.adjustment_distance

        self.shutdown_mode = False
        self.supervisor_id = args.supervisor_id

        self.client: Optional[cli.GripperClient] = None

        self.decoded_alarm_group = {False: 'No alarm was detected',
                                    'A': 'Unrecognized error',
                                    'B': 'Controller saved parameter issue',
                                    'C': 'Issue with position calibration',
                                    'D': 'Could not reach position within time limit',
                                    'E': 'General controller erorr'}

        agg_params = {'frame_length': 60}
        self.agent.register_feed('hwp_gripper', record=True, agg_params=agg_params)
        self.agent.register_feed('gripper_action', record=True)

    def _run_client_func(self, func, *args, lock_timeout=10,
                         job=None, check_shutdown=True, **kwargs):
        """
        Args
        ----
        func (function):
            Function to run
        *args (positional args):
            Additional args to pass to function
        lock_timeout (float):
            Time (sec) to wait to acquire client-lock before throwing an error.
        job (str):
            Name of job to attach to lock
        check_shutdown (bool):
            If true, will block the client function and throw an error if
            shutdown mode is in effect.
        """
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
            self.log.debug(line)
        return return_dict

    def _get_hwp_freq(self):
        if self.supervisor_id is None:
            raise ValueError("No Supervisor ID set")

        res = get_op_data(self.supervisor_id, 'monitor')
        return res['data']['hwp_state']['pid_current_freq']

    def _check_stopped(self):
        return self._get_hwp_freq() < 0.1

    def init_connection(self, session, params):
        """init_connection()

        **Task** - Initialize connection to the GripperServer on the BeagleBone
        micro-controller
        """
        if self._initialized:
            self.log.info('Connection already initialized. Returning...')
            return True, 'Connection already initialized'

        self.client = cli.GripperClient(self.mcu_ip, self.control_port)
        self.log.info("Initialized Client")
        self._initialized = True
        return True, 'Initialized connection to GripperServer'

    @ocs_agent.param('state', default=True, type=bool)
    def power(self, session, params=None):
        """power(state=True)

        **Task** - If turning on, will power on the linear actuators and disengage
        brakes. If turning off, will cut power to the linear actuators and engage
        brakes.

        Parameters:
            state (bool): State to set the actuator power to.

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["SVON turned on in Control.ON()",
                         "Turned off BRAKE for axis 1 in Control.BRAKE()",
                         "Turned off BRAKE for axis 2 in Control.BRAKE()",
                         "Turned off BRAKE for axis 3 in Control.BRAKE()",
                         "Successfully turned off BRAKE for axis 1 in Control.BRAKE()",
                         "Successfully turned off BRAKE for axis 2 in Control.BRAKE()",
                         "Successfully turned off BRAKE for axis 3 in Control.BRAKE()",
                         "Disengaged brakes in Control.ON()"]}
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

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Turned off BRAKE for axis 1 in Control.BRAKE()",
                         "Successfully turned off BRAKE for axis 1 in Control.BRAKE()"]}
        """
        return_dict = self._run_client_func(
            self.client.brake, params['state'], params['actuator'], job='brake'
        )
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('mode', default='push', type=str, choices=['push', 'pos'])
    @ocs_agent.param('actuator', default=1, type=int, check=lambda x: 1 <= x <= 3)
    @ocs_agent.param('distance', default=0, type=float)
    def move(self, session, params=None):
        """move(mode='push', actuator=1, distance=0)

        **Task** - Move an actuator a specific distance. If the HWP is spinning,
        this task will not run.

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

            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Control.STEP() operation finished for step 1",
                         "MOVE in Gripper.MOVE() completed successfully"]}
        """

        if self._get_hwp_freq() > 0.1:
            self.log.warn("Not moving actuators while HWP is spinning")
            return False, "HWP is spinning, not moving actuators"

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
            This action must be done first after a power cycle. Otherwise the
            controller will throw an error.

            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["SVON turned on in Control.ON()",
                         "'HOME' operation finished in Control.HOME()",
                         "HOME operation in Gripper.HOME() completed"]}
        """
        return_dict = self._run_client_func(self.client.home, job='home')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def inp(self, session, params=None):
        """inp()

        **Task** - Queries whether the actuators are in a known position. This
        tells you whether the windows software has detected that the actuator
        has been homed.

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': []}
        """
        return_dict = self._run_client_func(
            self.client.inp, job='INP', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def alarm(self, session, params=None):
        """alarm()

        **Task** - Queries the actuator controller alarm state

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["ALARM = False"]}
        """
        return_dict = self._run_client_func(
            self.client.alarm, job='alarm', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def alarm_group(self, session, params=None):
        """alarm_group()

        **Task** - Queries the actuator controller alarm group

        Notes:
            Return one of six values depending on the controller alarm state
                False: No alarm was detected
                'A': Unrecognized error
                'B': Controller saved parameter issue
                'C': Issue with position calibration
                'D': Could not reach position within time limit
                'E': General controller error

            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': 'B',
                 'log': ["ALARM GROUP B detected"]}
        """
        state_return_dict = self._run_client_func(
            self.client.get_state, job='get_state', check_shutdown=False)

        if not bool(state_return_dict['result']['jxc']['alarm']):
            return_dict = {'result': False, 'log': ['Alarm not triggered']}
        else:
            return_dict = self._run_client_func(
                self.client.alarm_group, job='alarm_group', check_shutdown=False)

            if return_dict['result'] is None:
                return_dict['result'] = 'A'

        session.data['response'] = return_dict
        session.data['decoded_alarm_group'] = self.decoded_alarm_group[return_dict['result']]
        return return_dict['result'], f"Success: {return_dict['result']}"

    def reset(self, session, params=None):
        """reset()
        **Task** - Resets the current active controller alarm

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Ignored Control.ALARM_GROUP(). No ALARM detected",
                         "RESET aborted in Gripper.RESET() due to no detected alarm"]}
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

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Actuator 1 is in state 1"]}
        """
        return_dict = self._run_client_func(
            self.client.act, params['actuator'], job='act', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('value', type=bool)
    def is_cold(self, session, params=None):
        """is_cold(value=False)

        **Task** - Set the limit switches to warm/cold grip configuration

        Parameters:
            value (bool): Set to warm grip (False) or cold grip (True)

        Notes:
            Configures the software to query the correct set of limit switches.
            Warm grip configuration enables both warm and cold limit switches.
            Cold grip configuration enables only cold limit switches. The maximum
            extension of the actuators depends on the cryostat temperature.

            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Received request to change is_cold to True",
                         "is_cold successfully changed"]}
        """
        return_dict = self._run_client_func(
            self.client.is_cold, params['value'], job='is_cold')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    @ocs_agent.param('value', default=False, type=bool)
    def force(self, session, params=None):
        """force(value=False)

        **Task** - Enable or disable force mode in the GripperServer,
        which will ignore limit switch information.

        Parameters:
            value (bool): Use limit switch information (False) or ignore limit
                switch information (True)

        Notes:
            By default the code is configured to prevent actuator movement if
            on of the limit switches has been triggered. This function can be
            called to forcibly move the actuators even with a limit switch
            trigger.

            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Received request to change force to True",
                         "force successfully changed"]}
        """
        return_dict = self._run_client_func(
            self.client.force, params['value'], job='force')
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def shutdown(self, session, params=None):
        """shutdown()

        **Task** - Series of commands executed during a shutdown.
        This will enable shutdown mode, which locks out other agent operations.

        Notes:
            This function is called once a shutdown trigger has been given.
        """
        self.log.info("Enabling shutdown-mode, which will prevent grip "
                      "operations from being performed")
        self.shutdown_mode = True
        return True, 'Shutdown completed'

    def grip(self, session, params=None):
        """grip()

        **Task** - Series of commands to automatically warm grip the HWP. This
        assumes that HWP is cold. This will return grippers to their home position,
        then move them each inwards incrementally until warm limit switches are
        tiggered. If the HWP is spinning, this will not run. If this fails to grip
        hwp, this will return grippers to their home position.

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['responses']
                [{'result': True, 'log': [.., .., etc]},
                                    ..
                 {'result': True, 'log': [.., .., etc]}]
        """
        if self._get_hwp_freq() > 0.1:
            return False, "Not gripping HWP because HWP is spinning"

        result, session.data = self._grip_hwp(check_shutdown=True)
        return result, "Finished gripping procedure"

    def _grip_hwp(self, check_shutdown=True):
        """
        Helper function to grip the HWP that can be called by the grip_hwp
        task or by the shutdown procedure.  This will return grippers to their
        home position, then move them each inwards incrementally.
        """
        data = {
            'responses': [],
        }

        def run_and_append(func, *args, **kwargs):
            return_dict = self._run_client_func(func, *args, **kwargs)
            data['responses'].append(return_dict)
            return return_dict

        # Check controller alarm
        return_dict = run_and_append(self.client.get_state, job='grip',
                                     check_shutdown=check_shutdown)
        if return_dict['result']['jxc']['alarm']:
            return_dict = self._run_client_func(
                self.client.alarm_group, job='alarm_group', check_shutdown=False)
            if return_dict['result'] is None:
                return_dict['result'] = 'A'
            alarm_message = self.decoded_alarm_group[return_dict['result']]
            self.log.error(
                f"Abort grip. Detected contoller alarm: {alarm_message}")
            return False, data

        # Check if hwp is already gripper or not
        act_results = return_dict['result']['actuators']
        limit_switch_state = act_results[0]['limits']['warm_grip']['state'] | \
            act_results[1]['limits']['warm_grip']['state'] | \
            act_results[2]['limits']['warm_grip']['state']
        if limit_switch_state:
            self.log.warn("HWP is already gripped. Do nothing.")
            return True, data

        # Reset alarms
        run_and_append(self.client.reset, job='grip', check_shutdown=check_shutdown)
        time.sleep(1)

        # Enable power to actuators
        run_and_append(self.client.power, True, job='grip', check_shutdown=check_shutdown)
        time.sleep(1)

        # Disable brake
        run_and_append(self.client.brake, False, job='grip', check_shutdown=check_shutdown)
        time.sleep(1)

        # Ignore limit switches to move grippers backwards
        run_and_append(self.client.force, True, job='grip', check_shutdown=check_shutdown)

        # Ensure that the limit switches are in warm configuration
        run_and_append(self.client.is_cold, False, job='grip', check_shutdown=check_shutdown)

        # Send grippers to their home position
        run_and_append(self.client.home, job='grip', check_shutdown=check_shutdown)

        # Ensure that we do not ignore limit switches
        run_and_append(self.client.force, False, job='grip', check_shutdown=check_shutdown)

        finished = [False, False, False]

        # Move to the warm_grip_distance - 5 mm.
        for actuator in range(3):
            distance = self.warm_grip_distance[actuator] - 5.
            return_dict = run_and_append(self.client.move, 'POS', actuator + 1, distance,
                                         job='grip', check_shutdown=check_shutdown)
            time.sleep(1)

        # Move actator inwards by 0.1 mm step, warm_grip_distance + 1 is absolute maximum
        for i in range(60):
            if all(finished):
                break
            for actuator, _ in enumerate(finished):
                if finished[actuator]:
                    continue

                # Move actuator inwards until warm-limit is hit
                # If the warm limit is hit, return_dict['result'] will be False
                return_dict = run_and_append(self.client.move, 'POS', actuator + 1, 0.1,
                                             job='grip', check_shutdown=check_shutdown)

                if not return_dict['result']:
                    # Reset alarms.
                    run_and_append(self.client.reset, job='grip',
                                   check_shutdown=check_shutdown)
                    time.sleep(1)

                    # If the warm-limit is hit, move the actuator outwards by 0.5 mm
                    # to un-trigger the warm-limit. This is because gripper sligthly
                    # overshoot the limit switches. The outward movement compensates
                    # for the overshoot and hysteresys of the limit switches.
                    run_and_append(self.client.is_cold, True, job='grip',
                                   check_shutdown=check_shutdown)
                    time.sleep(1)

                    run_and_append(self.client.move, 'POS', actuator + 1, -0.5,
                                   job='grip', check_shutdown=check_shutdown)

                    run_and_append(self.client.is_cold, False, job='grip',
                                   check_shutdown=check_shutdown)
                    time.sleep(1)

                    finished[actuator] = True

        # Return grippers back to home is something is wrong
        if not all(finished):
            self.log.error('Failed to grip HWP. Retract grippers.')
            run_and_append(self.client.force, True, job='grip',
                           check_shutdown=check_shutdown)
            time.sleep(1)

            run_and_append(self.client.home, job='grip',
                           check_shutdown=check_shutdown)
            time.sleep(1)

            run_and_append(self.client.force, False, job='grip',
                           check_shutdown=check_shutdown)

        # Adjust gripper position if you need
        else:
            run_and_append(self.client.is_cold, True, job='grip',
                           check_shutdown=check_shutdown)
            time.sleep(1)

            for actuator in range(3):
                run_and_append(self.client.move, 'POS', actuator + 1,
                               self.adjustment_distance[actuator],
                               job='grip', check_shutdown=check_shutdown)

            run_and_append(self.client.is_cold, False, job='grip',
                           check_shutdown=check_shutdown)
            time.sleep(1)

        # Enable breaks
        run_and_append(self.client.brake, True, job='grip',
                       check_shutdown=check_shutdown)
        time.sleep(1)

        # Disable power to actuators
        run_and_append(self.client.power, False, job='grip',
                       check_shutdown=check_shutdown)
        time.sleep(1)

        # We should stop schedule if we have an error in this task
        if not all(finished):
            self.log.error('Failed to grip HWP. Grippers are retracted.')
            return False, data

        return True, data

    def ungrip(self, session, params=None):
        """ungrip()

        **Task** - Series of commands to automatically ungrip the HWP.
        This will return grippers to their home position, and retract
        grippers as much as possible.

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['responses']
                [{'result': True, 'log': [.., .., etc]},
                                    ..
                 {'result': True, 'log': [.., .., etc]}]
        """

        result, session.data = self._ungrip_hwp(check_shutdown=True)
        return result, "Finished ungripping procedure"

    def _ungrip_hwp(self, check_shutdown=True):
        """
        Helper function to ungrip the HWP that can be called by the ungrip_hwp
        task or by the shutdown procedure.  This will return grippers to their
        home position, and retract as much as possible.
        """
        data = {
            'responses': [],
        }

        def run_and_append(func, *args, **kwargs):
            return_dict = self._run_client_func(func, *args, **kwargs)
            data['responses'].append(return_dict)
            return return_dict

        # Check controller alarm
        return_dict = run_and_append(self.client.get_state, job='ungrip',
                                     check_shutdown=check_shutdown)
        if return_dict['result']['jxc']['alarm']:
            return_dict = self._run_client_func(
                self.client.alarm_group, job='alarm_group', check_shutdown=False)
            if return_dict['result'] is None:
                return_dict['result'] = 'A'
            alarm_message = self.decoded_alarm_group[return_dict['result']]
            self.log.error(
                f"Abort ungrip. Detected contoller alarm: {alarm_message}")
            return False, data

        run_and_append(self.client.reset, job='ungrip', check_shutdown=check_shutdown)
        # Enable power to actuators
        run_and_append(self.client.power, True, job='ungrip', check_shutdown=check_shutdown)
        # Disable breaks
        run_and_append(self.client.brake, False, job='ungrip', check_shutdown=check_shutdown)
        # Ignore limit switches
        run_and_append(self.client.force, True, job='ungrip', check_shutdown=check_shutdown)

        # Send grippers to their home position
        run_and_append(self.client.home, job='ungrip', check_shutdown=check_shutdown)

        # Move actuator outwards as much as possible
        for actuator in range(1, 4):
            run_and_append(self.client.move, 'POS', actuator, -1.9,
                           job='ungrip', check_shutdown=check_shutdown)
        time.sleep(1)

        # Enable brake
        run_and_append(self.client.brake, True, job='ungrip', check_shutdown=check_shutdown)
        # Power off actuators
        run_and_append(self.client.power, False, job='ungrip', check_shutdown=check_shutdown)
        # Enable limit switches
        run_and_append(self.client.force, False, job='ungrip', check_shutdown=check_shutdown)
        time.sleep(1)

        # check limit switch state
        return_dict = run_and_append(self.client.get_state, job='ungrip',
                                     check_shutdown=check_shutdown)
        act_results = return_dict['result']['actuators']
        limit_switch_state = act_results[0]['limits']['warm_grip']['state'] | \
            act_results[1]['limits']['warm_grip']['state'] | \
            act_results[2]['limits']['warm_grip']['state']

        # Stop schedule if the limit switch state is wrong
        if limit_switch_state:
            self.log.error("Failed to ungrip HWP. Limit switch state is not as expected.")
            return False, data

        return True, data

    def cancel_shutdown(self, session, params=None):
        """cancel_shutdown()

        **Task** - Take the gripper agent out of shutdown mode
        """
        self.shutdown_mode = False
        return True, 'Cancelled shutdown mode'

    def restart(self, session, params=None):
        """restart()

        **Task** - Restarts the beaglebone processes and the socket connection

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Previous connection closed",
                         "Restart command response: Success",
                         "Control socket reconnected"]}
        """
        return_dict = self._run_client_func(
            self.client.restart, job='restart', check_shutdown=False)
        session.data['response'] = return_dict
        return return_dict['result'], f"Success: {return_dict['result']}"

    def monitor_state(self, session, params=None):
        """monitor_state()

        **Process** - Process to monitor the gripper state

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session
                {'last_updated': 1649085992.719602,
                 'state': {'last_packet_received': 1649085992.719602,
                           'jxc_setup': False,
                           'jxc_svon': False,
                           'jxc_busy': False,
                           'jxc_seton': False,
                           'jxc_inp': False,
                           'jxc_svre': False,
                           'jxc_alarm': False,
                           'jxc_alarm_message': 'No alarm was detected',
                           'jxc_out': 0,
                           'act{axis}_pos': 0,
                           'act{axis}_limit_warm_grip_state': False,
                           'act{axis}_limit_cold_grip_state': False,
                           'act{axis}_emg': False,
                           'act{axis}_brake': True}}
        """
        sleep_time = 5
        while session.status in ['starting', 'running']:
            if self.client is None:
                self.log.warn("Client not initialized")
                time.sleep(1)
                continue

            try:
                return_dict = self._run_client_func(
                    self.client.get_state, job='get_state', check_shutdown=False
                )
            except TimeoutError:
                self.log.warn('monitor_state: Query Timeout')

            now = time.time()

            # Dict of the 'GripperState' class from the pru_monitor
            state = return_dict['result']
            data = {
                'last_packet_received': state['last_packet_received'],
            }

            data.update({
                'jxc_setup': int(state['jxc']['setup']),
                'jxc_svon': int(state['jxc']['svon']),
                'jxc_busy': int(state['jxc']['busy']),
                'jxc_seton': int(state['jxc']['seton']),
                'jxc_inp': int(state['jxc']['inp']),
                'jxc_svre': int(state['jxc']['svre']),
                'jxc_alarm': int(state['jxc']['alarm']),
                'jxc_out': int(state['jxc']['out']),
            })

            alarm_group_mapping = {4: 'B',
                                   2: 'C',
                                   1: 'D',
                                   0: 'E'}

            if bool(state['jxc']['alarm']):
                out_value = int(state['jxc']['out']) % 16
                if out_value in alarm_group_mapping.keys():
                    alarm_message = self.decoded_alarm_group[alarm_group_mapping]
                else:
                    alarm_message = self.decoded_alarm_group['A']
            else:
                alarm_message = self.decoded_alarm_group[False]

            data.update({'jxc_alarm_message': alarm_message})

            for act in state['actuators']:
                axis = act['axis']
                data.update({
                    f'act{axis}_pos': act['pos'],
                    f'act{axis}_limit_cold_grip_state': int(act['limits']['cold_grip']['state']),
                    f'act{axis}_limit_warm_grip_state': int(act['limits']['warm_grip']['state']),
                    f'act{axis}_brake': int(act['brake']),
                    f'act{axis}_emg': int(act['emg']),
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

    @ocs_agent.param('no_data_warn_time', default=60, type=float)
    @ocs_agent.param('no_data_shutdown_time', default=300, type=float)
    def monitor_supervisor(self, session, params=None):
        """monitor_supervisor(no_data_warn_time=60, no_data_shutdown_time=300)

        **Process** - Monitor the hwp-supervisor state. If supervisor sends shutdown
        signal, or if communication wtih supervisor is dropped for longer than
        ``no_data_shutdown_time``, this will begin agent shutdown and disable access
        to other dangerous gripper operations.

        Parameters:
            no_data_warn_time (int): Time in seconds to wait after communication failure
                                     before generating a warning
            no_data_shutdown_time (int): Time in seconds to wait after communication failure
                                         before initiating shutdown

        Notes:
            The most recent data collected is stored in session data in the
            structure:

                >>> response.session
                {'time': 1649085992.719602,
                 'gripper_action': 'ok'}
        """
        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, 'No supervisor ID set'

        warning_issued = False
        while session.status in ['starting', 'running']:
            res = get_op_data(self.supervisor_id, 'monitor')
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['gripper']

            if action == 'ok':
                warning_issued = False
                last_ok_time = time.time()
            elif action == 'stop':
                if not self.shutdown_mode:
                    self.agent.start('shutdown')

            time_since_ok = time.time() - last_ok_time
            if time_since_ok > params['no_data_warn_time'] and not warning_issued:
                self.log.error(
                    f"Have not received 'ok' in {time_since_ok / 60:.2f} minutes."
                    f"Will issue shutdown in "
                    f"{params['no_data_shutdown_time'] / 60:.2f} minutes."
                )
                warning_issued = True

            if time_since_ok > params['no_data_shutdown_time']:
                self.log.error(
                    f"Have not received 'ok' in "
                    f"{params['no_data_shutdown_time'] / 60:.2f} minutes. "
                    "Issuing shutdown"
                )
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

            time.sleep(1)
        return True, 'Gripper monitor exited cleanly'

    def _stop_monitor_supervisor(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting monitor_supervisor process to stop"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--mcu-ip', type=str,
                        help='IP of Gripper Beaglebone')
    pgroup.add_argument('--control-port', type=int, default=8041,
                        help='Port for actuator control as set by the Beaglebone code')
    pgroup.add_argument('--warm-grip-distance', action='store', type=float, nargs=3,
                        default=[10.0, 10.0, 10.0],
                        help='Nominal distance for warm grip position (mm). This needs'
                             'to be multiple of 0.1')
    pgroup.add_argument('--adjustment-distance', action='store', type=float, nargs=3,
                        default=[0, 0, 0],
                        help='Adjustment distance to compensate the misalignment of '
                             'limit switches (mm). This needs to be multiple of 0.1')
    pgroup.add_argument('--supervisor-id', type=str,
                        help='Instance ID for HWP Supervisor agent')
    pgroup.add_argument('--no-data-warn-time', type=float, default=60,
                        help='Time (seconds) since last supervisor-ok signal to '
                             'wait before issuing a warning')
    pgroup.add_argument('--no-data-shutdown-time', type=float, default=300,
                        help='Time (seconds) since last supervisor-ok signal to '
                             'wait before entering shutdown mode')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPGripperAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    gripper_agent = HWPGripperAgent(agent, args)
    agent.register_task('init_connection', gripper_agent.init_connection,
                        startup=True)
    agent.register_process('monitor_state', gripper_agent.monitor_state,
                           gripper_agent._stop_monitor_state, startup=True)
    agent.register_process('monitor_supervisor', gripper_agent.monitor_supervisor,
                           gripper_agent._stop_monitor_supervisor,
                           startup={'no_data_warn_time': args.no_data_warn_time,
                                    'no_data_shutdown_time': args.no_data_shutdown_time})
    agent.register_task('power', gripper_agent.power)
    agent.register_task('brake', gripper_agent.brake)
    agent.register_task('move', gripper_agent.move)
    agent.register_task('home', gripper_agent.home)
    agent.register_task('inp', gripper_agent.inp)
    agent.register_task('alarm', gripper_agent.alarm)
    agent.register_task('alarm_group', gripper_agent.alarm_group)
    agent.register_task('reset', gripper_agent.reset)
    agent.register_task('act', gripper_agent.act)
    agent.register_task('is_cold', gripper_agent.is_cold)
    agent.register_task('force', gripper_agent.force)
    agent.register_task('shutdown', gripper_agent.shutdown)
    agent.register_task('grip', gripper_agent.grip)
    agent.register_task('ungrip', gripper_agent.ungrip)
    agent.register_task('cancel_shutdown', gripper_agent.cancel_shutdown)
    agent.register_task('restart', gripper_agent.restart)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
