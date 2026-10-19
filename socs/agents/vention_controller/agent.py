import argparse
from operator import pos
import os
import time

import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from machinelogic import Machine, MotionProfile, ActuatorGroup

def get_profile(agent, velocity, acceleration):
    """Select the motion profile to use for a movement.

    If both velocity and acceleration are given, build a new
    MotionProfile from them. If neither is given, fall back to the
    profile stored by set_motion_profile.

    Returns:
        tuple: (profile, error_message). Exactly one will be None.

    """
    if (velocity is None) != (acceleration is None):
        return None, "Specify both velocity and acceleration, or neither to use the profile from set_motion_profile."
    if velocity is not None:
        return MotionProfile(velocity=velocity, acceleration=acceleration), None
    if agent.profile is None:
        return None, "No profile set; run set_motion_profile first, or pass velocity and acceleration."
    return agent.profile, None

class VentionControllerAgent:
    """ Agent for controlling Vention actuator motors used in LAT FTS
    coupling optics instrument for passband measurements on-site.

    Args:
        ip (str): IP address for the Vention actuator controller
        port (int, optional): TCP port for controller communication.
            Default is 23
    """

    def __init__(self, agent, ip, port=23):
        self.lock = TimeoutLock()
        self.agent = agent
        self.log = agent.log
        self.ip = ip
        self.port = port

        self.initialized = False
        self.take_data = False

        self.stage = None
        self.profile = None
        self.group = None
        self.axes = {}

        # Register data feeds
        agg_params = {
            'frame_length': 60,
        }

        self.agent.register_feed('stage_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', type=bool, default=False)
    def init(self, session, params=None):
        """init(auto_acquire=False)

        **Task** - Initalize connection to Vention controller.

        Parameters:
            auto_acquire(bool):  If True, start acquisition immediately after
                initialization. Defaults to False.

        """
        if self.initialized:
            return True, "Already initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            # Establish connection
            self.stage = Machine(self.ip)

            # Define actuator axes, which also tests the connection
            try:
                self.axes = {name.lower(): self.stage.get_actuator(name)
                             for name in ("X", "Y", "Z")}
            except ConnectionError:
                self.log.error("Could not establish connection to Vention controller")
                return False, "Vention Controller agent initialization failed"

            # Define actuator group for easy movement of all axes together.
            # Axis order (x, y, z) sets the order of move targets.
            self.group = ActuatorGroup(*self.axes.values())

        self.initialized = True

        # start data acquistion if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Vention Controller agent initialized"

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acquisition of data from the Vention Controller.

        Parameters:
            test_mode (bool, optional): Run the process loop only once.
                This is meant only for testing. Default is False.

        Notes:
            The data collected is stored in session data in the structure:

                >> response.session['data']
                {'fields': {'xpos':0.0, 'xvel':0.0, 'xhome':0.0, 'xend':0.0, 
                            'ypos':0.0, 'yvel':0.0, 'yhome':0.0, 'yend':0.0, 
                            'zpos':0.0, 'zvel':0.0, 'zhome':0.0, 'zend':0.0}}, 
                            'timestamp': 1764009732.0866072}

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} is already running")
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            pm = Pacemaker(1 / 3, quantize=False)
            while self.take_data:
                pm.sleep()
                # Reliqinuish sampling lock occassionally
                if time.time() - last_release > 1:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                try:
                    data = {}
                    for name, axis in self.axes.items():
                        data[f'{name}pos'] = axis.state.position
                        data[f'{name}vel'] = axis.state.speed
                        data[f'{name}home'], data[f'{name}end'] = int(axis.state.end_sensors[0]), int(axis.state.end_sensors[1])
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from Vention controller. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue

                session.data = {"fields": data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'axes',
                            'data': data}

                self.agent.publish_to_feed('stage_status', pub_data)

                if params['test_mode']:
                    break

        self.agent.feeds['stage_status'].flush_buffer()

        return True, 'Acquisition exited cleanly.'
    
    def _stop_acq(self, session, params):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('velocity', type=float)
    @ocs_agent.param('acceleration', type=float)
    def set_motion_profile(self, session, params):
        """set_motion_profile(velocity, acceleration)

        **Task** - Set the motion profile (i.e. velocity and acceleration) for the stages in self.profile.

        Parameters:
            velocity (float): The velocity to use, in mm/s.
            acceleration (float): The acceleration to use, in mm/s^2.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."
        velocity = params['velocity']
        acceleration = params['acceleration']
        with self.lock.acquire_timeout(timeout=5, job='set_motion_profile') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                                f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # set motion profile
            self.profile = MotionProfile(velocity=velocity, acceleration=acceleration)
        return True, f"Commanded stages to set motion profile with velocity={velocity}, acceleration={acceleration}."


    @ocs_agent.param('distances', type=list)
    @ocs_agent.param('velocity', default=None, type=float)
    @ocs_agent.param('acceleration', default=None, type=float)
    def set_relative_position(self, session, params):
        """set_relative_position(distances, velocity=None, acceleration=None)

        **Task** - Set the relative 3D position location for the stages.

        Parameters:
            distances (list): A list of relative (x,y,z) distance values, in millimeters.
            velocity (float, optional): The velocity to use for the movement, in mm/s.
            acceleration (float, optional): The acceleration to use for the movement, in mm/s^2.

        Notes:
            velocity and acceleration must be given together. If neither is
            given, the profile from set_motion_profile is used.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."
        distances = params['distances']

        profile, err = get_profile(self, params['velocity'], params['acceleration'])
        if err:
            return False, err

        with self.lock.acquire_timeout(timeout=5, job='home') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                                f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.group.move_relative_async(distances, profile)

        return True, f"Commanded stages to move by relative distances: {distances}."

    @ocs_agent.param('distances', type=list)
    @ocs_agent.param('velocity', default=None, type=float)
    @ocs_agent.param('acceleration', default=None, type=float)
    def set_absolute_position(self, session, params):
        """set_absolute_position(distances, velocity=None, acceleration=None)

        **Task** - Set the absolute 3D position location for the stages.

        Parameters:
            distances (list): A list of absolute (x,y,z) position values, in millimeters.
            velocity (float, optional): The velocity to use for the movement, in mm/s.
            acceleration (float, optional): The acceleration to use for the movement, in mm/s^2.

        Notes:
            velocity and acceleration must be given together. If neither is
            given, the profile from set_motion_profile is used.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."
        distances = params['distances']

        profile, err = get_profile(self, params['velocity'], params['acceleration'])
        if err:
            return False, err

        with self.lock.acquire_timeout(timeout=5, job='home') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                                f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.group.move_absolute_async(distances, profile)

        return True, f"Commanded stages to move to absolute position: {distances}."

    @ocs_agent.param('timeout', type=float, default=60)
    def wait_for_move(self, session, params):
        """wait_for_move(timeout=60)

        **Task** - Wait for the current move to finish. Note that acq cannot happen while this task is running.

        Parameters:
            timeout (float, optional): The timeout for waiting for the move to finish, in seconds. Default is 60.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."

        with self.lock.acquire_timeout(timeout=5, job='wait_for_move') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            try:
                self.group.wait_for_move_completion(params['timeout'])
            except Exception as e:
                self.log.error(f"Move did not complete: {e}")
                return False, f"Move did not complete within {params['timeout']:.1f} s: {e}"

        return True, "Move completed successfully."

    @ocs_agent.param('timeout', default=60., type=float)
    def home(self, session, params):
        """home(timeout=60)

        **Task** - Home the stages, one axis at a time, in x, y, z order.

        Parameters:
            timeout (float, optional): The timeout for homing each axis, in
                seconds. Default is 60.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."

        # Only hold the lock while checking for other motion, so acq keeps
        # sampling during homing
        with self.lock.acquire_timeout(timeout=5, job='home') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

        try:
            for name, axis in self.axes.items():
                self.log.info(f"Homing {name} axis")
                axis.home(timeout=params['timeout'])
        except Exception as e:
            self.log.error(f"Homing {name} axis failed: {e}")
            return False, f"Homing {name} axis failed: {e}"

        return True, "Homed all axes."

    def check_sensors(self, session, params=None):
        """check_sensors()

        **Task** - Return the current [home, end] sensor states for each axis.

        """
        if not self.initialized:
            return False, "Agent not initialized; run init first."

        states = {name: axis.state.end_sensors for name, axis in self.axes.items()}
        return True, f"[home, end] sensor states: {states}"

def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip')
    pgroup.add_argument('--port', default=23)
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='VentionControllerAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False,
                       }
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True,
                       }

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    # create agent instance and run log creation
    ventioncontroller_agent = VentionControllerAgent(agent, args.ip)

    agent.register_task('init', ventioncontroller_agent.init, startup=init_params)
    agent.register_task('set_motion_profile', ventioncontroller_agent.set_motion_profile)
    agent.register_task('set_relative_position', ventioncontroller_agent.set_relative_position)
    agent.register_task('set_absolute_position', ventioncontroller_agent.set_absolute_position)
    agent.register_task('wait_for_move', ventioncontroller_agent.wait_for_move)
    agent.register_task('home', ventioncontroller_agent.home)
    agent.register_task('check_sensors', ventioncontroller_agent.check_sensors)
    agent.register_process('acq', ventioncontroller_agent.acq, ventioncontroller_agent._stop_acq)
    
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    from multiprocessing import resource_tracker

    resource_tracker.ensure_running()
    main()