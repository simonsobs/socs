import time
import os
import txaio
import argparse

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock, Pacemaker

on_rtd = os.environ.get('READTHEDOCS') == True
if not on_rtd:
    from sat1_motors_driver import MotControl


class SAT1MotorsAgent:
    """
    Agent for connecting to the SAT1 XY Stages. Differs from LATRt agent in that 
    motors/controllers are seen as arguments.
    Motor1 can be the X axis OR the Y axis, same with Motor2. Depends on setup 
    (ip address + port).

    Args:
        motor1_ip (str) : the IP address associated with Motor1
        motor1_port (int) : the port address associated with Motor1
        motor1_is_lin (bool) : Boolean that determines if Motor1 is a linear motor.
        motor2_ip (str) : the IP address associated with Motor2
        motor2_port (int) : the port address associated with Motor2
        motor2_is_lin (bool) : Boolean that determines if Motor2 is a linear motor.
        mode: 'acq' : Start data acquisition on initialize
        m_res (bool) : True if manual resolution, False if default (res=8)
        samp : default sampling frequency in Hz
    """

    def __init__(
            self,
            agent,
            motor1_ip,
            motor1_port,
            motor1_is_lin,
            motor2_ip,
            motor2_port,
            motor2_is_lin,
            m_res,
            mode=None,
            samp=2):

        self.job = None
        # Pass these through site config
        self.motor1_ip = motor1_ip
        self.motor1_port = motor1_port
        self.motor1_is_lin = motor1_is_lin
        self.motor2_ip = motor2_ip
        self.motor2_port = motor2_port
        self.motor2_is_lin = motor2_is_lin
        self.m_res = m_res
        self.sampling_frequency = samp
        self.move_status = False

        self.motors = None
        self.initialized = False
        self.take_data = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        if mode == 'acq':
            self.auto_acq = True
        else:
            self.auto_acq = False
        self.sampling_frequency = float(samp)

        # register the position feeds
        agg_params = {
            'frame_length': 10 * 60,  # [sec]
        }

        self.agent.register_feed('positions',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def init_motors_task(self, session, params=None):
        """init_motors_task(params=None):
        
        **Task** - Connect to the motors, either one or both.

        Parameters:
            params (dict): Parameters dictionary for passing 
                parameters to task.
        """

        if params is None:
            params = {}
        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn(
                    "Could not start init because {} is already running".format(
                        self.lock.job))
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")
            self.motors = MotControl(
                motor1_ip=self.motor1_ip,
                motor1_port=self.motor1_port,
                motor1_is_lin=self.motor1_is_lin,
                motor2_ip=self.motor2_ip,
                motor2_port=self.motor2_port,
                motor2_is_lin=self.motor2_is_lin,
                m_res=self.m_res)

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Motor(s) Initialized.'

    def move_axis_to_position(self, session, params=None):
        """move_axis_to_position(motor=1, pos=0, pos_is_inches=False,
            lin_stage=True):
        
        ** Task** - Move the axis to the given absolute position in counts or 
        inches.
        
        .. note:: 
            If moving multiple axes, function will assume ``lin_stage`` value 
            for all axes.
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos (float): The desired position in counts or in inches, positive 
                indicates away from the motor (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False 
                if in counts (default False)
            lin_stage (bool): True if the specified motor is for the linear 
                stage, False if not (default True)
        """

        lin_stage = params.get('lin_stage', True)
        motor = params.get('motor', 1)
        pos_is_inches = params.get('pos_is_inches', False)
        pos = params.get('pos', 0)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f'move_axis_to_position_motor{motor}') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move motor{motor} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.move_axis_to_position(motor, pos, pos_is_inches, lin_stage)

        return True, "Moved motor {} to {}".format(motor, pos)

    def move_axis_by_length(self, session, params=None):
        """move_axis_by_length(motor=1, pos=0, pos_is_inches=False, 
            lin_stage=True):
        
        **Task** - Move the axis relative to the current position by the 
        specified number of counts or inches.
            
        .. note:: 
            If moving multiple axes, function will assume ``lin_stage`` value 
                for all axes.
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos (float): The desired position in counts or in inches, positive 
                indicates away from the motor. (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
            lin_stage (bool): True if the specified motor is for the linear 
                stage, False if not (default True)
        """

        lin_stage = params.get('lin_stage', True)
        motor = params.get('motor', 1)
        pos = params.get('pos', 0)
        pos_is_inches = params.get('pos_is_inches', False)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f'move_axis_by_length_motor{motor}') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move motor{motor} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.move_axis_by_length(motor, pos, pos_is_inches, lin_stage)

        return True, "Moved motor {} by {}".format(motor, pos)

    def set_velocity(self, session, params=None):
        """set_velocity(motor=1, velocity=0.25):
        
        **Task** - Set velocity of motors driving stages.
        
        Parameter:
            motor (int):Determines which motor, either 1 or 2, 3 is for all
                motors.(default 3)
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 12.0)
        """

        motor = params.get('motor', 3)
        velocity = params.get('velocity', 12.0)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(timeout=1, job=f'set_velocity{motor}') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set_velocity because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.set_velocity(motor, velocity)

        return True, "Set velocity of motor {} to {}".format(motor, velocity)

    def set_acceleration(self, session, params=None):
        """set_acceleration(motor=1, accel=1):
        
        **Task** - Set acceleration of motors driving stages.
        
        .. note::
            `accel` parameter will only accept integer values.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 1)
        """

        motor = params.get('motor', 3)
        accel = params.get('accel', 1.0)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(timeout=1, job=f'set_acceleration_motor{motor}') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set_acceleration because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.set_acceleration(motor, accel)

        return True, "Set acceleration of motor {} to {}".format(motor, accel)

    def start_jogging(self, session, params=None):
        """start_jogging(motor=1):
        
        **Task** - Jogs the motor(s) set by params.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"start_jogging_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            self.motors.start_jogging(motor)

        return True, "Started jogging motor {}".format(motor)

    def stop_jogging(self, session, params=None):
        """stop_jogging(motor=1):
        
        **Task** - Stops the jogging of motor(s) set by params.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"stop_jogging_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not stop_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            self.motors.stop_jogging(motor)

        return True, "Stopped jogging motor {}".format(motor)

    def seek_home_linear_stage(self, session, params=None):
        """seek_home_linear_stage(motor=1):
        
        **Task** - Move the linear stage to its home position (using the home
        limit switch).
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(timeout=1, job=f'seek_home_linear_stage_motor{motor}') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not seek_home_linear_stage because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.seek_home_linear_stage(motor)

        return True, "Moving motor {} to home".format(motor)

    def set_zero(self, session, params=None):
        """set_zero(motor=1):
        
        **Task** - Sets the zero position (AKA home) for motor(s) specified in
        params.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f"set_zero_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not set_zero because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            self.motors.set_zero(motor)

        return True, "Zeroing motor {} position".format(motor)

    def run_positions(self, session, params=None):
        """run_positions(motor=1, pos_data=file.tsv, pos_is_inches=False):
        
        **Task** - Runs a tab-delimited list of entries as positions from a 
        text file.  For motor=3, the first column must be the x-data, and
        the second column the y-data.  Each position will be attained. 
        xPosition and yPosition will be specified as in the file.
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos_data (.tsv file): Tab-delimited list of entries. First column
                is x-data, second column is y-data.
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
        """

        motor = params.get('motor', 1)
        pos_is_inches = params.get('pos_is_inches', True)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f"run_positions_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not run_positions because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            self.motors.run_positions(params['pos_data'], motor, pos_is_inches)

        return True, "Moving stage to {}".format(params['pos_data'])

    def start_rotation(self, session, params=None):
        """start_rotation(motor=1, velocity=0.25, accel=1):
        
        **Task** - Start rotating motor of polarizer. 
        
        .. note:: 
            Give acceleration and velocity values as arguments here.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            velocity (float): The rotation velocity in revolutions per second
                within range [0.25,50]. (default 12.0)
            accel (float): The acceleration in revolutions per second per
                second within range [1,3000]. (default 1.0)
        """

        motor = params.get('motor', 1)
        velocity = params.get('velocity', 12.0)
        accel = params.get('accel', 1.0)
        with self.lock.acquire_timeout(1, job=f"start_rotation_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not start_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.start_rotation(motor, velocity, accel)

        return True, "Started rotating motor at velocity {} and acceleration {}".format(
            velocity, accel)

    def stop_rotation(self, session, params=None):
        """stop_rotation(motor=1):
        
        **Task** - Stop rotating motor of polarizer.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"stop_rotation_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not stop_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            self.motors.stop_rotation(motor)

        return True, "Stopped rotating motor"

    def close_connection(self, session, params=None):
        """close_connection(motor=1):
        
        **Task** - Close connection to specific motor.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"close_connection_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not close connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motors.close_connection(motor)

        return True, "Closed connection to motor {}".format(motor)

    def reconnect_motor(self, session, params=None):
        """reconnect_motor(motor=1):
        
        **Task** - Reestablish a connection to a motor if connection is lost.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"reconnect_motor_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not reestablish connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motors.reconnect_motor(motor)
        return True, "Reestablished connection with motor{}".format(motor)

    def block_while_moving(self, session, params=None):
        """block_while_moving(motor=1, update_period=.1, verbose=False):
        
        **Task** - Block until the specified axes/motor have stop moving. 
        Checks each axis every update_period seconds.
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            updatePeriod (float): Time after which to check each motor in 
                seconds. (default .1)
            verbose (bool): Prints output from motor requests if True. 
                (default False)
        """

        motor = params.get('motors', 1)
        update_period = params.get('update_period', .1)
        verbose = params.get('verbose', False)
        with self.lock.acquire_timeout(1, job=f"block_while_moving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not block_while_moving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motors.block_while_moving(motor, update_period, verbose)

        return True, "Motor {} stopped moving".format(motor)

    def kill_all_commands(self, session, params=None):
        """kill_all_commands(motor=1):
        
        **Task** Stops all active commands on the device. Does not interact
        with lock file...
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"kill_all_commands_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not kill_all_commands because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motors.kill_all_commands(motor)

        return True, "Killing all active commands on motor {}".format(motor)

    def set_encoder_value(self, session, params=None):
        """set_encoder_value(motor=1, value=0):
        
        **Task** - Set the encoder values in order to keep track of absolute
            position.
            
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            value (float): Sets encoder value. (default 0)
        """

        motor = params.get('motor', 1)
        value = params.get('value', 0)
        self.move_status = self.motors.is_moving(motor)
        if self.move_status:
            return False, "Motors are already moving."

        with self.lock.acquire_timeout(1, job=f"set_encoder_value_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not set_encoder_value because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            ePositions = self.motors.set_encoder_value(motor, value)

        return True, "Setting encoder position to {}".format(ePositions)

    def get_encoder_value(self, session, params=None):
        """get_encoder_value(motor=1):
        
        **Task** - Retrieve all motor step counts to verify movement.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"get_encoder_info_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_encoder_info because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            ePositions = self.motors.retrieve_encoder_info(motor)

        return True, ("Current encoder positions: {}".format(
            ePositions), ePositions)

    def get_positions(self, session, params=None):
        """get_positions(motor=1, inches=True):
        
        **Task** - Get the position of the motor in counts, relative to the
        set zero point (or starting point/home).

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            inches (bool): Whether to return positions in inches or not.
                (default True)
                
        Returns:
            positions (list): The positions of the specified motors.
        """

        motor = params.get('motor', 1)
        inches = params.get('inches', True)
        with self.lock.acquire_timeout(1, job=f"get_positions_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_positions because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if inches:
                positions = self.motors.get_position_in_inches(motor)
            elif not inches:
                positions = self.motors.get_position(motor)
            else:
                return False, "Invalid choice for inches parameter, must be boolean"

        return True, "Current motor positions: {}".format(positions)

    def pos_while_moving(self, session, params=None):
        """pos_while_moving(motor=1, inches=True):
        
        **Task** - Get the position of the motor while it is currently in 
        motion. An estimate based on the calculated trajectory of the movement,
        relative to the zero point.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            inches (bool): Whether to return positions in inches or not.
                (default True)
                
        Returns:
            positions (list): The positions of the specified motors.
        """

        inches = params.get('inches', True)
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"pos_while_moving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not pos_while_moving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            i_positions = self.motors.get_immediate_position(motor, inches)

        return True, "Current motor positions: {}".format(i_positions)

    def is_moving(self, session, params=None):
        """is_moving(motor=1, verbose=True):
        
        **Tasks** - Checks if motors are moving OR if limit switches are 
        tripped.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """
        verbose = params.get('verbose', True)
        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"is_moving_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            self.move_status = self.motors.is_moving(motor, verbose)

        if self.move_status:
            return True, ("Motors are moving.", self.move_status)
        else:
            return True, ("Motors are not moving.", self.move_status)

    def move_off_limit(self, session, params=None):
        """move_off_limit(motor=1):
        
        **Task** - Moves motor off limit switch if unexpectedly hit, resetting
        alarms.
        
        Parameters:
            motor (int): 1,2,3. Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        motor = params.get('motor', 3)
        with self.lock.acquire_timeout(1, job=f"move_off_limit{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move_off_limit because lock held by {self.lock.job}")
                return False
            self.motors.move_off_limit(motor)

        return True, "Motor {} moved off limit switch".format(motor)

    def reset_alarms(self, session, params=None):
        """reset_alarms(motor=1):
        
        **Task** - Resets alarm codes present. Only advised if you have checked
        what the alarm is first!
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(1, job=f"reset_alarms_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not reset_alarms because lock held by {self.lock.job}")
                return False
            self.motors.reset_alarms(motor)

        return True, "Alarms reset for motor {}".format(motor)

    def home_with_limits(self, session, params=None):
        """home_with_limits(motor=1):
        
        **Task** - Moves stages to home based on location from limits. One inch
        from the limit switch.
        
        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        motor = params.get('motor', 1)
        with self.lock.acquire_timeout(30, job=f"home_with_limits_motor{motor}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move motor{motor} to home because lock held by {self.lock.job}")
                return False
            self.motors.home_with_limits(motor)

        return True, "Zeroed stages using limit switches"

    def start_acq(self, session, params=None):
        """start_acq(motor=1, verbose=False, sampling_freqency=2):
        
        **Process** - Start acquisition of data.
        
        Parameter:
        motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        verbose (bool): Prints output from motor requests if True. 
            (default False)
        sampling_frequency (float): Sampling rate in Hz. (default 2)
        """
        if params is None:
            params = {}

        motor = params.get('motor', 3)
        verbose = params.get('verbose', False)
        f_sample = params.get('sampling_frequency', self.sampling_frequency)
        pm = Pacemaker(f_sample, quantize=True)

        if not self.initialized or self.motors is None:
            raise Exception("Connection to motors is not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    "Could not start acq because {} is already running".format(
                        self.lock.job))
                return False, "Could not acquire lock."
            self.log.info(
                f"Starting data acquisition for stages at {f_sample} Hz")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

            mList = self.motors.gen_motor_list(motor)
            while self.take_data:
                if time.time() - last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(
                            f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False, "could not re-acquire lock"
                    last_release = time.time()
                pm.sleep()
                data = {
                    'timestamp': time.time(),
                    'block_name': 'positions',
                    'data': {}}

                for mot in mList:
                    mot_id = mot.propDict['motor']
                    try:
                        self.log.debug(
                            f"getting position/move status of motor{mot_id}")
                        self.move_status = self.motors.is_moving(
                            mot_id, verbose)
                        pos = self.motors.get_position_in_inches(motor=mot_id)
                        if self.move_status:
                            data['data'][f'motor{mot_id}_encoder'] = -1
                        else:
                            ePos = self.motors.retrieve_encoder_info(
                                motor=mot_id)
                            data['data'][f'motor{mot_id}_encoder'] = ePos[0]
                        data['data'][f'motor{mot_id}_stepper'] = pos[0]
                        data['data'][f'motor{mot_id}_connection'] = 1

                    except Exception as e:
                        self.log.debug(f'error: {e}')
                        self.log.debug(
                            f"could not get position/move status of motor{mot_id}")
                        data['data'][f'motor{mot_id}_encoder'] = 0
                        data['data'][f'motor{mot_id}_stepper'] = 0.0
                        data['data'][f'motor{mot_id}_connection'] = 0

                self.agent.publish_to_feed('positions', data)

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """stop_acq(params=None):
        
        **Task** - Stop data acquisition.
        
        Parameters:
            None
        """

        if self.take_data:
            self.take_data = False
            return True, 'Requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """

    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--motor1-ip', help="MOXA IP address", type=str)
    pgroup.add_argument(
        '--motor1-port',
        help="MOXA port number for motor 1",
        type=int)
    pgroup.add_argument(
        '--motor1-is-lin',
        action='store_true',
        help="Whether or not motor 1 is connected to a linear stage")
    pgroup.add_argument('--motor2-ip', help="MOXA IP address", type=str)
    pgroup.add_argument(
        '--motor2-port',
        help="MOXA port number for motor 1",
        type=int)
    pgroup.add_argument(
        '--motor2-is-lin',
        action='store_true',
        help="Whether or not motor 2 is connected to a linear stage")
    pgroup.add_argument(
        '--m-res',
        help="Manually enter microstep resolution",
        action='store_true')
    pgroup.add_argument(
        '--sampling-frequency',
        help="Frequency to sample at for data acq",
        type=float)
    pgroup.add_argument(
        '--mode',
        help="puts mode into auto acquisition or not...",
        type=str)

    return parser


if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    # Parse comand line.
    parser = make_parser()
    args = site_config.parse_args(agent_class='SAT1MotorsAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    m = SAT1MotorsAgent(
        agent,
        args.motor1_ip,
        args.motor1_port,
        args.motor1_is_lin,
        args.motor2_ip,
        args.motor2_port,
        args.motor2_is_lin,
        args.m_res,
        args.mode,
        args.sampling_frequency)

    agent.register_task('init_motors', m.init_motors_task)
    agent.register_task('move_to_position', m.move_axis_to_position)
    agent.register_task('move_by_length', m.move_axis_by_length)
    agent.register_task('move_motors', m.move_motors)
    agent.register_task('set_velocity', m.set_velocity)
    agent.register_task('set_accel', m.set_acceleration)
    agent.register_task('start_jog', m.start_jogging)
    agent.register_task('stop_jog', m.stop_jogging)
    agent.register_task('seek_home', m.seek_home_linear_stage)
    agent.register_task('set_zero', m.set_zero)
    agent.register_task('run_positions', m.run_positions)
    agent.register_task('start_rotation', m.start_rotation)
    agent.register_task('stop_rotation', m.stop_rotation)
    agent.register_task('close_connect', m.close_connection)
    agent.register_task('reconnect_motor', m.reconnect_motor)
    agent.register_task('block_while_moving', m.block_while_moving)
    agent.register_task('kill_all', m.kill_all_commands)
    agent.register_task('set_encoder', m.set_encoder_value)
    agent.register_task('get_encoder', m.get_encoder_value)
    agent.register_task('get_position', m.get_positions)
    agent.register_task('is_moving', m.is_moving)
    agent.register_task('get_imm_position', m.pos_while_moving)
    agent.register_task('move_off_limit', m.move_off_limit)
    agent.register_task('reset_alarm', m.reset_alarms)
    agent.register_task('home_with_limits', m.home_with_limits)

    agent.register_process('acq', m.start_acq, m.stop_acq)

    runner.run(agent, auto_reconnect=True)
