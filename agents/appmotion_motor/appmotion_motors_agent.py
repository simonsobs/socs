import time
import os
import txaio
import argparse

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock, Pacemaker

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from appmotion_motors_driver import Motor


class appMotionMotorsAgent:
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
        """init_motors_task(params=None)

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

            self.log.debug("Lock Acquired Connecting to Stages")

            print('establishing serial server with motor1!')
            self.motor1 = Motor(self.motor1_ip, self.motor1_port, self.motor1_is_lin, self.mot_id='motor1', self.index=MOTOR1, self.m_res=m_res)
            print('establishing serial server with motor2!')
            self.motor2 = Motor(self.motor2_ip, self.motor2_port, self.motor2_is_lin, self.mot_id='motor2', self.index=MOTOR2, self.m_res=m_res)

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Motor(s) Initialized.'

    @ocs_agent.param('lin_stage', default=True, type=bool)
    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('pos_is_inches', default=False, type=bool)
    @ocs_agent.param('pos', default=0, type=float)
    def move_axis_to_position(self, session, params=None):
        """move_axis_to_position(motor=1, pos=0, pos_is_inches=False,
            lin_stage=True)

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
        
        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(1, job=f'move_axis_to_position_motor{'motor'}') as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not move motor{'motor'} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.move_axis_to_position('pos', 'pos_is_inches', 'lin_stage')
            elif 'motor'==2:
                self.motor2.move_axis_to_position('pos', 'pos_is_inches', 'lin_stage')
            elif 'motor'==3:
                self.motor1.move_axis_to_position('pos', 'pos_is_inches', 'lin_stage')
                self.motor2.move_axis_to_position('pos', 'pos_is_inches', 'lin_stage')
            else:
                print("Motor ID invalid argument")

        return True, "Moved motor {} to {}".format('motor', 'pos')
    
    @ocs_agent.param('lin_stage', default=True, type=bool)
    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('pos_is_inches', default=False, type=bool)
    @ocs_agent.param('pos', default=0, type=float)
    def move_axis_by_length(self, session, params=None):
        """move_axis_by_length(motor=1, pos=0, pos_is_inches=False,
            lin_stage=True)

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

        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(1, job=f'move_axis_by_length_motor{'motor'}') as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not move motor{'motor'} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.move_axis_by_length('pos', 'pos_is_inches', 'lin_stage')
            elif 'motor'==2:
                self.motor2.move_axis_by_length('pos', 'pos_is_inches', 'lin_stage')
            elif 'motor'==3:
                self.motor1.move_axis_by_length('pos', 'pos_is_inches', 'lin_stage')
                self.motor2.move_axis_by_length('pos', 'pos_is_inches', 'lin_stage')
            else:
                print("Motor ID invalid argument")

        return True, "Moved motor {} by {}".format('motor', 'pos')

    @ocs_agent.param('motor', default=3, type=int)
    @ocs_agent.param('velocity', default=12.0, type=float, check=lambda x: 0.25 <= x <= 50)
    def set_velocity(self, session, params=None):
        """set_velocity(motor=1, velocity=0.25)

        **Task** - Set velocity of motors driving stages.

        Parameter:
            motor (int):Determines which motor, either 1 or 2, 3 is for all
                motors.(default 3)
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 12.0)
        """

        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(timeout=1, job=f'set_velocity{'motor'}') as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_velocity because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.set_velocity('velocity')
            elif 'motor'==2:
                self.motor2.set_velocity('velocity')
            elif 'motor'==3:
                self.motor1.set_velocity('velocity')
                self.motor2.set_velocity('velocity')
            else:
                print("Motor ID invalid argument")

        return True, "Set velocity of motor {} to {}".format('motor', 'velocity')
    
    @ocs_agent.param('motor', default=3, type=int)
    @ocs_agent.param('accel', default=1, type=int, check=lambda x: 1 <= x <= 3000)
    def set_acceleration(self, session, params=None):
        """set_acceleration(motor=3, accel=1)

        **Task** - Set acceleration of motors driving stages.

        .. note::
            `accel` parameter will only accept integer values.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 1)
        """
        
        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(timeout=1, job=f'set_acceleration_motor{'motor'}') as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_acceleration because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.set_acceleration('accel')
            elif 'motor'==2:
                self.motor2.set_acceleration('accel')
            elif 'motor'==3:
                self.motor1.set_acceleration('accel')
                self.motor2.set_acceleration('accel')
            else:
                print("Motor ID invalid argument")

        return True, "Set acceleration of motor {} to {}".format('motor', 'accel')
    
    @ocs_agent.param('motor', default=1, type=int)
    def start_jogging(self, session, params=None):
        """start_jogging(motor=1)

        **Task** - Jogs the motor(s) set by params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """
        
        with self.lock.acquire_timeout(1, job=f"start_jogging_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if 'motor'==1:
                self.motor1.start_jogging()
            elif 'motor'==2:
                self.motor2.start_jogging()
            elif 'motor'==3:
                self.motor1.start_jogging()
                self.motor2.start_jogging()
            else:
                print("Motor ID invalid argument")

        return True, "Started jogging motor {}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def stop_jogging(self, session, params=None):
        """stop_jogging(motor=1)
        **Task** - Stops the jogging of motor(s) set by params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """
        
        with self.lock.acquire_timeout(1, job=f"stop_jogging_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not stop_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if 'motor'==1:
                self.motor1.stop_jogging()
            elif 'motor'==2:
                self.motor2.stop_jogging()
            elif 'motor'==3:
                self.motor1.stop_jogging()
                self.motor2.stop_jogging()
            else:
                print("Motor ID invalid argument")

        return True, "Stopped jogging motor {}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def seek_home_linear_stage(self, session, params=None):
        """seek_home_linear_stage(motor=1)

        **Task** - Move the linear stage to its home position (using the home
        limit switch).

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """
        
        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(timeout=1, job=f'seek_home_linear_stage_motor{'motor'}') as acquired
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not seek_home_linear_stage because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.seek_home_linear_stage()
            elif 'motor'==2:
                self.motor2.seek_home_linear_stage()
            elif 'motor'==3:
                self.motor1.seek_home_linear_stage()
                self.motor2.seek_home_linear_stage()
            else:
                print("Motor ID invalid argument")

        return True, "Moving motor {} to home".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def set_zero(self, session, params=None):
        """set_zero(motor=1)

        **Task** - Sets the zero position (AKA home) for motor(s) specified in
        params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(1, job=f"set_zero_motor{'motor'}") as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not set_zero because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if 'motor'==1:
                self.motor1.set_zero()
            elif 'motor'==2:
                self.motor2.set_zero()
            elif 'motor'==3:
                self.motor1.set_zero()
                self.motor2.set_zero()
            else:
                print("Motor ID invalid argument")

        return True, "Zeroing motor {} position".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    @ocs_agent.param('pos_data', type=list)
    def run_positions(self, session, params=None):
        """run_positions(pos_data=None, motor=1, pos_is_inches=False)

        **Task** - Runs a list of entries as positions. For
        motor=ALL, the first column must be the x-data, and the second column
        the y-data. Each position will be attained.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos_data (list): Tab-delimited list of entries. First column
                is x-data, second column is y-data.
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
        """

        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(1, job=f"run_positions_motor{'motor'}") as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not run_positions because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            # This is for the 2-axis case.  In the 1-axis case, pos_data[0] will just be a floating point value
            if (len('pos_data') > 0):
                if 'motor' == 3 and len('pos_data') < 2:
                    raise Exception(
                        "You specified that both axes would be moving, but didn't provide data for both.")
            if 'motor'==1:
                self.motor1.run_positions('pos_data', 'pos_is_inches')
            elif 'motor'==2:
                self.motor2.run_positions('pos_data', 'pos_is_inches')
            elif 'motor'==3:
                self.motor1.run_positions('pos_data[0]', 'pos_is_inches')
                self.motor2.run_positions('pos_data[1]', 'pos_is_inches')
            else:
                print("Motor ID invalid argument")

        return True, "Moving stage to {}".format(params['pos_data'])

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('velocity', default=12.0, type=float, check=lambda x: 0.25 <= x <= 50)
    @ocs_agent.param('rot_accel', default=1.0, type=float, check=lambda x: 1.0 <= x <= 3000)
    def start_rotation(self, session, params=None):
        """start_rotation(motor=1, velocity=12.0, rot_accel=1.0)

        **Task** - Start rotating motor of polarizer.

        .. note::
            Give acceleration and velocity values as arguments here.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            velocity (float): The rotation velocity in revolutions per second
                within range [0.25,50]. (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000]. (default 1.0)
        """

        with self.lock.acquire_timeout(1, job=f"start_rotation_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not start_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.start_rotation('velocity', 'rot_accel')
            elif 'motor'==2:
                self.motor2.start_rotation('velocity', 'rot_accel')
            elif 'motor'==3:
                self.motor1.start_rotation('velocity', 'rot_accel')
                self.motor2.start_rotation('velocity', 'rot_accel')
            else:
                print("Motor ID invalid argument")

        return True, "Started rotating motor at velocity {} and acceleration {}".format(
            'velocity', 'rot_accel')

    @ocs_agent.param('motor', default=1, type=int)
    def stop_rotation(self, session, params=None):
        """stop_rotation(motor=1)

        **Task** - Stop rotating motor of polarizer.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"stop_rotation_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not stop_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.stop_rotation()
            elif 'motor'==2:
                self.motor2.stop_rotation()
            elif 'motor'==3:
                self.motor1.stop_rotation()
                self.motor2.stop_rotation()
            else:
                print("Motor ID invalid argument")

        return True, "Stopped rotating motor"

    @ocs_agent.param('motor', default=3, type=int)
    def close_connection(self, session, params=None):
        """close_connection(motor=3)

        **Task** - Close connection to specific motor.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"close_connection_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not close connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.close_connection()
            elif 'motor'==2:
                self.motor2.close_connection()
            elif 'motor'==3:
                self.motor1.close_connection()
                self.motor2.close_connection()
            else:
                print("Motor ID invalid argument")

        return True, "Closed connection to motor {}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def reconnect_motor(self, session, params=None):
        """reconnect_motor(motor=1)

        **Task** - Reestablish a connection to a motor if connection is lost.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """
        
        with self.lock.acquire_timeout(1, job=f"reconnect_motor_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not reestablish connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.reconnect_motor()
            elif 'motor'==2:
                self.motor2.reconnect_motor()
            elif 'motor'==3
                self.motor1.reconnect_motor()
                self.motor2.reconnect_motor()
            else:
                print("Motor ID invalid argument")

        if Motor.reconnect_motor.sock_status == 1:
            return True, "Reestablished connection with motor{}".format('motor')
        elif Motor.reconnect_motor.sock_status == 0:
            return False, "Failed to reestablish connection with motor{}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('update_period', default=.1, type=float)
    @ocs_agent.param('verbose', default=False, type=bool)
    def block_while_moving(self, session, params=None):
        """block_while_moving(motor=1, update_period=.1, verbose=False)

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

        with self.lock.acquire_timeout(1, job=f"block_while_moving_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not block_while_moving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.block_while_moving('update_period', 'verbose')
            elif 'motor'==2:
                self.motor2.block_while_moving('update_period', 'verbose')
            elif 'motor'==3:
                self.motor1.block_while_moving('update_period', 'verbose')
                self.motor2.block_while_moving('update_period', 'verbose')
            else:
                print("Motor ID invalid argument")

        return True, "Motor {} stopped moving".format('motor')

    @ocs_agent.param('motor', default=3, type=int)
    def kill_all_commands(self, session, params=None):
        """kill_all_commands(motor=3)

        **Task** Stops all active commands on the device.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """
        
        with self.lock.acquire_timeout(1, job=f"kill_all_commands_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not kill_all_commands because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'motor'==1:
                self.motor1.kill_all_commands()
            elif 'motor'==2:
                self.motor2.kill_all_commands()
            elif 'motor'==3:
                self.motor1.kill_all_commands()
                self.motor2.kill_all_commands()
            else:
                print("Motor ID invalid argument")

        return True, "Killing all active commands on motor {}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('value', default=0, type=float)
    def set_encoder_value(self, session, params=None):
        """set_encoder_value(motor=1, value=0)

        **Task** - Set the encoder values of given motor(s) to one specified 
        value in order to keep track of absolute position.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            value (float): Sets encoder value. (default 0)
        """
        
        self.move_status = self.is_moving('motor')[1][1]
        with self.lock.acquire_timeout(1, job=f"set_encoder_value_motor{'motor'}") as acquired:
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not set_encoder_value because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if 'motor'==1:
                e_positions=self.motor1.set_encoder_value('value')
            elif 'motor'==2:
                e_positions=self.motor2.set_encoder_value('value')
            elif 'motor'==3:
                e_positions=self.motor1.set_encoder_value('value')
                e_positions=self.motor2.set_encoder_value('value')
            else:
                print("Motor ID invalid argument")

        return True, "Setting encoder position of motor {} to {}".format('motor', e_positions)

    @ocs_agent.param('motor', default=3, type=int)
    def get_encoder_value(self, session, params=None):
        """get_encoder_value(motor=3)

        **Task** - Retrieve all motor step counts to verify movement.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"get_encoder_info_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_encoder_info because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if 'motor'==1:
                e_positions=self.motor1.retrieve_encoder_info()
            elif 'motor'==2:
                e_positions=self.motor2.retrieve_encoder_info()
            elif 'motor'==3:
                e_positions=self.motor1.retrieve_encoder_info()
                e_positions=self.motor2.retrieve_encoder_info()
            else:
                print("Motor ID invalid argument")

        return True, ("Current encoder positions: {}".format(
            e_positions), e_positions)

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    def get_positions(self, session, params=None):
        """get_positions(motor=1, inches=True)

        **Task** - Get the position of the motor in counts, relative to the
        set zero point (or starting point/home).

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos_is_inches (bool): Whether to return positions in inches or not.
                (default True)

        Returns:
            positions (list): The positions of the specified motors.
        """

        with self.lock.acquire_timeout(1, job=f"get_positions_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_positions because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'pos_is_inches':
                if 'motor'==1:
                    positions=self.motor1.get_position_in_inches()
                elif 'motor'==2:
                    positions=self.motor2.get_position_in_inches()
                elif 'motor'==3:
                    positions=self.motor1.get_position_in_inches()
                    positions=self.motor2.get_position_in_inches()
                else:
                    print("Motor ID invalid argument")
            elif not 'pos_is_inches':
                if 'motor'==1:
                    positions=self.motor1.get_position()
                elif 'motor'==2:
                    positions=self.motor2.get_position()
                elif 'motor'==3:
                    positions=self.motor1.get_position()
                    positions=self.motor2.get_position()
                else:
                    print("Motor ID invalid argument")
            else:
                return False, "Invalid choice for inches parameter, must be boolean"

        return True, "Current motor positions: {}".format(positions)

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    def pos_while_moving(self, session, params=None):
        """pos_while_moving(motor=1, inches=True)

        **Task** - Get the position of the motor while it is currently in
        motion. An estimate based on the calculated trajectory of the movement,
        relative to the zero point.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos_is_inches (bool): Whether to return positions in inches or not.
                (default True)

        Returns:
            positions (list): The positions of the specified motors.
        """

        with self.lock.acquire_timeout(1, job=f"pos_while_moving_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not pos_while_moving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if 'motor'==1:
                i_positions=self.motor1.get_immediate_position('pos_is_inches')
            elif 'motor'==2:
                i_positions=self.motor2.get_immediate_position('pos_is_inches')
            elif 'motor'==3:
                i_positions=self.motor1.get_immediate_position('pos_is_inches')
                i_positions=self.motor2.get_immediate_position('pos_is_inches')
            else:
                print("Motor ID invalid argument")

        return True, "Current motor positions: {}".format(i_positions)

    @ocs_agent.param('motor', default=1, type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def is_moving(self, session, params=None):
        """is_moving(motor=1, verbose=True)

        **Tasks** - Checks if motors are moving OR if limit switches are
        tripped.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(1, job=f"is_moving_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            if 'motor'==1:
                self.move_status=self.motor1.is_moving('verbose')
            elif 'motor'==2:
                self.move_status=self.motor2.is_moving('verbose')
            elif 'motor'==3:
                self.move_status=self.motor1.is_moving('verbose')
                self.move_status=self.motor2.is_moving('verbose')
            else:
                print("Motor ID invalid argument")

        if self.move_status:
            return True, ("Motors are moving.", self.move_status)
        else:
            return True, ("Motors are not moving.", self.move_status)

    @ocs_agent.param('motor', default=3, type=int)
    def move_off_limit(self, session, params=None):
        """move_off_limit(motor=3)

        **Task** - Moves motor off limit switch if unexpectedly hit, resetting
        alarms.

        Parameters:
            motor (int): 1,2,3. Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"move_off_limit{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move_off_limit because lock held by {self.lock.job}")
                return False
            if 'motor'==1:
                self.motor1.move_off_limit()
            elif 'motor'==2:
                self.motor2.move_off_limit()
            elif 'motor'==3:
                self.motor1.move_off_limit()
                self.motor2.move_off_limit()
            else:
                print("Motor ID invalid argument")
                      
        return True, "Motor {} moved off limit switch".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def reset_alarms(self, session, params=None):
        """reset_alarms(motor=1)

        **Task** - Resets alarm codes present. Only advised if you have checked
        what the alarm is first!

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"reset_alarms_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not reset_alarms because lock held by {self.lock.job}")
                return False
            if 'motor'==1:
                self.motor1.reset_alarms()
            elif 'motor'==2:
                self.motor2.reset_alarms()
            elif 'motor'==3:
                self.motor1.reset_alarms()
                self.motor2.reset_alarms()
            else:
                print("Motor ID invalid argument.")

        return True, "Alarms reset for motor {}".format('motor')

    @ocs_agent.param('motor', default=1, type=int)
    def home_with_limits(self, session, params=None):
        """home_with_limits(motor=1)

        **Task** - Moves stages to home based on location from limits. One inch
        from the limit switch.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(30, job=f"home_with_limits_motor{'motor'}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not move motor{'motor'} to home because lock held by {self.lock.job}")
                return False
            if 'motor'==1:
                self.motor1.home_with_limits()
            elif 'motor'==2:
                self.motor2.home_with_limits()
            elif 'motor'==3:
                self.motor1.home_with_limits()
                self.motor2.home_with_limits()
            else:
                print("Motor ID invalid argument.")

        return True, "Zeroed stages using limit switches"

    @ocs_agent.param('motor', default=3, type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    @ocs_agent.param('f_sample', default=2, type=float)
    def start_acq(self, session, params=None):
        """start_acq(motor=3, verbose=False, f_sample=2)

        **Process** - Start acquisition of data.

        The ``session.data`` object stores the most recent published values
        in a dictionary. For example::

            session.data = {
                'timestamp': 1598626144.5365012,
                'block_name': 'positions',
                'data': {
                    "motor1_encoder": 15000,
                    "motor1_stepper": 12,
                    "motor1_connection": 1,
                    "motor1_move_status": False,
                }
            }

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                    motors. (default 3)
            verbose (bool): Prints output from motor requests if True.
                (default False)
            f_sample (float): Sampling rate in Hz. (default 2)
        """
        if params is None:
            params = {}
            
        pm = Pacemaker('f_sample', quantize=True)

        if not self.initialized:
            raise Exception("Connection to motors is not initialized")
        elif self.motor1 is None and self.motor2 is None:
            raise Exception("Connection to motors is not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    "Could not start acq because {} is already running".format(
                        self.lock.job))
                return False, "Could not acquire lock."
            self.log.info(
                f"Starting data acquisition for stages at {'f_sample'} Hz")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

            mot_list = [self.motor1, self.motor2]
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

                for mot in mot_list:
                    if mot.mot_id is None:
                        continue
                    try:
                        self.log.debug(
                            f"getting position/move status of motor{'motor'}")
                        self.move_status = mot.is_moving('verbose')
                        pos = mot.get_position_in_inches()
                        if self.move_status:
                            data['data'][f'motor{mot}_encoder'] = -1
                        else:
                            e_pos = mot.retrieve_encoder_info()
                            data['data'][f'motor{'motor'}_encoder'] = e_pos[0]
                        data['data'][f'motor{'motor'}_stepper'] = pos[0]
                        data['data'][f'motor{'motor'}_connection'] = 1
                        data['data'][f'motor{'motor'}_move_status'] = self.move_status

                    except Exception as e:
                        self.log.debug(f'error: {e}')
                        self.log.debug(
                            f"could not get position/move status of motor{'motor'}")
                        data['data'][f'motor{'motor'}_encoder'] = 0
                        data['data'][f'motor{'motor'}_stepper'] = 0.0
                        data['data'][f'motor{'motor'}_connection'] = 0

                self.agent.publish_to_feed('positions', data)
                session.data = data

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """stop_acq(params=None)

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
    args = site_config.parse_args(agent_class='appMotionMotorsAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    m = appMotionMotorsAgent(
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
