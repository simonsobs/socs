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
        self.samp = float(samp)
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

        # register the position feeds
        agg_params = {
            'frame_length': 10 * 60,  # [sec]
        }

        self.agent.register_feed('positions',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def init_motors(self, session, params=None):
        """init_motors()

        **Task** - Connect to the motors, either one or both.

        """

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
            self.motor1 = Motor(self.motor1_ip, self.motor1_port, self.motor1_is_lin, mot_id='motor1', index=1, m_res=self.m_res)
            print('establishing serial server with motor2!')
            self.motor2 = Motor(self.motor2_ip, self.motor2_port, self.motor2_is_lin, mot_id='motor2', index=2, m_res=self.m_res)

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Motor(s) Initialized.'

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def movement_check(self, params):
        """movement_check(motor=1, verbose)

        **Helper Function** - Checks if motors are moving OR
        if limit switches are tripped.
        Used within tasks to check movement status.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        Returns:
            status (bool): Movement status, True if motor is moving,
                False if not.
        """
        if params['motor'] == 1:
            status = self.motor1.is_moving(params['verbose'])
        elif params['motor'] == 2:
            status = self.motor2.is_moving(params['verbose'])
        else:
            status = self.motor1.is_moving(params['verbose']) or self.motor2.is_moving(params['verbose'])

        return status

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def is_moving(self, session, params):
        """is_moving(motor=1, verbose=True)

        **Tasks** - Checks if motors are moving OR if limit switches are
        tripped.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """
        with self.lock.acquire_timeout(1, job=f"is_moving_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            self.move_status = self.movement_check(params)

        if self.move_status:
            return True, ("Motors are moving.", self.move_status)
        else:
            return True, ("Motors are not moving.", self.move_status)

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', defualt=True, type=bool)
    def motor_reset(self, session, params):
        """motor_reset(motor=1)

        **Tasks** - Resets the motor and leaves in disabled state

        Parameters:
        -----------
            motor (int): Determines which motor (Default 1)
            verbose (bool): For move_status check. (Default True)
        """
        with self.lock.acquire_timeout(1, job=f"motor_reset_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are still moving, exiting'
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.motor_reset()
            elif params['motor'] == 2:
                self.motor2.motor_reset()
            else:
                self.motor1.motor_reset()
                self.motor2.motor_reset()
        return True, "Motors reset!"

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('enable', default=True, type=bool)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_motor_enable(self, session, params):
        """set_motor_enable(motor=1, enable=True)

        **Tasks** - Enables or disables specified motor

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            enable (bool): Enables (disables) motor if True (False)
            verbose (bool): For move_status check. (Default True)
        """

        with self.lock.acquire_timeout(1, job=f"motor_enable_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are still moving, exiting'
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.set_motor_enable(params['enable'])
            elif params['motor'] == 2:
                self.motor2.set_motor_enable(params['enable'])
            else:
                self.motor1.set_motor_enable(params['enable'])
                self.motor2.set_motor_enable(params['enable'])

        if params['enable']:
            return True, "motor enabled!"
        else:
            return True, "motor disabled!"

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('gearing', default=20000, check=lambda x: 200 <= x <= 32000, type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_gearing(self, session, params):
        """set_gearing(motor=1, gearing=20000)

        **Tasks** - Sets electronic gearing of motor to {gearing} pules/revolution.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            gearing (int): Sets pulse per revolution ratio.
                Range: [200,32000]
            verbose (bool): Print message received from motor via driver
                (Default True)
        """
        with self.lock.acquire_timeout(1, job=f"motor_set_gearing_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are still moving, exiting'
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.set_gearing(params['gearing'], params['verbose'])
            elif params['motor'] == 2:
                self.motor2.set_gearing(params['gearing'], params['verbose'])
            else:
                self.motor1.set_gearing(params['gearing'], params['verbose'])
                self.motor2.set_gearing(params['gearing'], params['verbose'])

            return True, f"Gearing set to {params['gearing']}!"

    @ocs_agent.param('lin_stage', default=True, type=bool)
    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('pos_is_inches', default=False, type=bool)
    @ocs_agent.param('pos', default=0, type=float)
    @ocs_agent.param('verbose', default=True, type=bool)
    def move_axis_to_position(self, session, params):
        """move_axis_to_position(motor=1, pos=0, pos_is_inches=False,\
        lin_stage=True)

        **Task** - Move the axis to the given absolute position in counts or
        inches.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos (float): The desired position in counts or in inches, positive
                indicates away from the motor (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False
                if in counts (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not (default True)
            verbose (bool): Prints output from motor requests if True.
                (default True)

        .. note::
            If moving multiple axes, function will assume ``lin_stage`` value
            for all axes.

        """

        with self.lock.acquire_timeout(1, job=f'move_axis_to_position_motor{params["motor"]}') as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are still moving, exiting'
            if not acquired:
                self.log.warn(
                    f"Could not move motor{params['motor']} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.move_axis_to_position(params['pos'], params['pos_is_inches'], params['lin_stage'])
            elif params['motor'] == 2:
                self.motor2.move_axis_to_position(params['pos'], params['pos_is_inches'], params['lin_stage'])
            else:
                # move motor1 THEN motor2
                self.motor1.move_axis_to_position(params['pos'], params['pos_is_inches'], params['lin_stage'])
                # could probably use movement_check here
                self.move_status = self.motor1.is_moving(params['verbose'])
                while self.move_status:
                    self.move_status = self.motor1.is_moving(params['verbose'])
                    time.sleep(1)
                self.motor2.move_axis_to_position(params['pos'], params['pos_is_inches'], params['lin_stage'])

        return True, "Moved motor {} to {}".format(params['motor'], params['pos'])

    @ocs_agent.param('lin_stage', default=True, type=bool)
    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('pos_is_inches', default=False, type=bool)
    @ocs_agent.param('pos', default=0, type=float)
    @ocs_agent.param('verbose', default=True, type=bool)
    def move_axis_by_length(self, session, params):
        """move_axis_by_length(motor=1, pos=0, pos_is_inches=False,\
        lin_stage=True)

        **Task** - Move the axis relative to the current position by the
        specified number of counts or inches.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos (float): The desired position in counts or in inches, positive
                indicates away from the motor. (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not (default True)

        .. note::
            If moving multiple axes, function will assume ``lin_stage`` value
            for all axes.

        """

        with self.lock.acquire_timeout(1, job=f"move_axis_by_length_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are still moving, exiting'
            if not acquired:
                self.log.warn(
                    f"Could not move motor{params['motor']} because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.move_axis_by_length(params['pos'], params['pos_is_inches'], params['lin_stage'])
            elif params['motor'] == 2:
                self.motor2.move_axis_by_length(params['pos'], params['pos_is_inches'], params['lin_stage'])
            else:
                # move motor1 THEN motor2
                self.motor1.move_axis_by_length(params['pos'], params['pos_is_inches'], params['lin_stage'])
                self.move_status = self.motor1.is_moving(params['verbose'])
                while self.move_status:
                    self.move_status = self.motor1.is_moving(params['verbose'])
                    time.sleep(1)
                self.motor2.move_axis_by_length(params['pos'], params['pos_is_inches'], params['lin_stage'])

        return True, "Moved motor {} by {}".format(params['motor'], params['pos'])

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    @ocs_agent.param('velocity', default=12.0, type=float, check=lambda x: 0.25 <= x <= 50)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_velocity(self, session, params):
        """set_velocity(motor=1, velocity=0.25)

        **Task** - Set velocity of motors driving stages.

        Parameters:
            motor (int):Determines which motor, either 1 or 2, 3 is for all
                motors.(default 3)
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 12.0)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(timeout=1, job=f'set_velocity{params["motor"]}') as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_velocity because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.set_velocity(params['velocity'])
            elif params['motor'] == 2:
                self.motor2.set_velocity(params['velocity'])
            else:
                self.motor1.set_velocity(params['velocity'])
                self.motor2.set_velocity(params['velocity'])

        return True, "Set velocity of motor {} to {}".format(params['motor'], params['velocity'])

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    @ocs_agent.param('accel', default=1, type=int, check=lambda x: 1 <= x <= 3000)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_acceleration(self, session, params):
        """set_acceleration(motor=3, accel=1)

        **Task** - Set acceleration of motors driving stages.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(timeout=1, job=f'set_acceleration_motor{params["motor"]}') as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_acceleration because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.set_acceleration(params['accel'])
            elif params['motor'] == 2:
                self.motor2.set_acceleration(params['accel'])
            else:
                self.motor1.set_acceleration(params['accel'])
                self.motor2.set_acceleration(params['accel'])

        return True, "Set acceleration of motor {} to {}".format(params['motor'], params['accel'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    def start_jogging(self, session, params):
        """start_jogging(motor=1)

        **Task** - Jogs the motor(s) set by params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"start_jogging_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if params['motor'] == 1:
                self.motor1.start_jogging()
            elif params['motor'] == 2:
                self.motor2.start_jogging()
            else:
                self.motor1.start_jogging()
                self.motor2.start_jogging()

        return True, "Started jogging motor {}".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    def stop_jogging(self, session, params):
        """stop_jogging(motor=1)
        **Task** - Stops the jogging of motor(s) set by params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"stop_jogging_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not stop_jogging because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if params['motor'] == 1:
                self.motor1.stop_jogging()
            elif params['motor'] == 2:
                self.motor2.stop_jogging()
            else:
                self.motor1.stop_jogging()
                self.motor2.stop_jogging()

        return True, "Stopped jogging motor {}".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_zero(self, session, params):
        """set_zero(motor=1)

        **Task** - Sets the zero position (AKA home) for motor(s) specified in
        params.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(1, job=f"set_zero_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not set_zero because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if params['motor'] == 1:
                self.motor1.set_zero()
            elif params['motor'] == 2:
                self.motor2.set_zero()
            else:
                self.motor1.set_zero()
                self.motor2.set_zero()

        return True, "Zeroing motor {} position".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    @ocs_agent.param('pos_data', type=list)
    @ocs_agent.param('verbose', default=True, type=bool)
    def run_positions(self, session, params):
        """run_positions(pos_data=None, motor=1, pos_is_inches=False)

        **Task** - Takes (up to) two elements in a list, and runs each motor
        to their respective position.
        If motor==3, Motor1 moves to the first element,
        motor2 to the second element in the list. Can be different positions,
        thus differentiating this task from other movement tasks.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            pos_data (list): Up to 2 element list of positions
                for motors to go to.
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(1, job=f"run_positions_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not run_positions because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            # This is for the 2-axis case.  In the 1-axis case, pos_data[0] will just be a floating point value
            if (len(params['pos_data']) > 0):
                if params['motor'] == 3 and len(params['pos_data']) < 2:
                    raise Exception(
                        "You specified that both axes would be moving, but didn't provide data for both.")
            if params['motor'] == 1:
                self.motor1.run_positions(params['pos_data'][0], params['pos_is_inches'])
            elif params['motor'] == 2:
                self.motor2.run_positions(params['pos_data'][0], params['pos_is_inches'])
            else:
                # move motor1 THEN motor2
                self.motor1.run_positions(params['pos_data'][0], params['pos_is_inches'])
                self.move_status = self.motor1.is_moving(params['verbose'])
                while self.move_status:
                    time.sleep(1)
                    self.move_status = self.motor1.is_moving(params['verbose'])
                self.motor2.run_positions(params['pos_data'][1], params['pos_is_inches'])

        return True, "Moving stages to {}".format(params['pos_data'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('velocity', default=12.0, type=float, check=lambda x: 0.25 <= x <= 50)
    @ocs_agent.param('rot_accel', default=1.0, type=float, check=lambda x: 1.0 <= x <= 3000)
    def start_rotation(self, session, params):
        """start_rotation(motor=1, velocity=12.0, rot_accel=1.0)

        **Task** - Start rotating motor of polarizer.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            velocity (float): The rotation velocity in revolutions per second
                within range [0.25,50]. (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000]. (default 1.0)
        """

        with self.lock.acquire_timeout(1, job=f"start_rotation_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not start_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.start_rotation(params['velocity'], params['rot_accel'])
            elif params['motor'] == 2:
                self.motor2.start_rotation(params['velocity'], params['rot_accel'])
            else:
                self.motor1.start_rotation(params['velocity'], params['rot_accel'])
                self.motor2.start_rotation(params['velocity'], params['rot_accel'])

        return True, "Started rotating motor at velocity {} and acceleration {}".format(
            'velocity', 'rot_accel')

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    def stop_rotation(self, session, params):
        """stop_rotation(motor=1)

        **Task** - Stop rotating motor of polarizer.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"stop_rotation_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not stop_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.stop_rotation()
            elif params['motor'] == 2:
                self.motor2.stop_rotation()
            else:
                self.motor1.stop_rotation()
                self.motor2.stop_rotation()

        return True, "Stopped rotating motor"

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    def close_connection(self, session, params):
        """close_connection(motor=3)

        **Task** - Close connection to specific motor.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
            force (bool): Close connection without checking lock-file.
        """
        with self.lock.acquire_timeout(1, job=f"close_connection_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not close connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.close_connection()
            elif params['motor'] == 2:
                self.motor2.close_connection()
            else:
                self.motor1.close_connection()
                self.motor2.close_connection()

        return True, "Closed connection to motor {}".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    def reconnect_motor(self, session, params):
        """reconnect_motor(motor=1)

        **Task** - Reestablish a connection to a motor if connection is lost.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"reconnect_motor_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not reestablish connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.reconnect_motor()
            elif params['motor'] == 2:
                self.motor2.reconnect_motor()
            else:
                self.motor1.reconnect_motor()
                self.motor2.reconnect_motor()

        return True, "Motor{} reconnection task completed".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('update_period', default=.1, type=float)
    @ocs_agent.param('verbose', default=False, type=bool)
    def block_while_moving(self, session, params):
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

        with self.lock.acquire_timeout(1, job=f"block_while_moving_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not block_while_moving because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.block_while_moving(params['update_period'], params['verbose'])
            elif params['motor'] == 2:
                self.motor2.block_while_moving(params['update_period'], params['verbose'])
            elif params['motor'] == 3:
                self.motor1.block_while_moving(params['update_period'], params['verbose'])
                self.motor2.block_while_moving(params['update_period'], params['verbose'])
            else:
                print("Motor ID invalid argument")

        return True, "Motor {} stopped moving".format(params['motor'])

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    def kill_all_commands(self, session, params):
        """kill_all_commands(motor=3)

        **Task** - Stops all active commands on the device.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"kill_all_commands_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not kill_all_commands because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                self.motor1.kill_all_commands()
            elif params['motor'] == 2:
                self.motor2.kill_all_commands()
            else:
                self.motor1.kill_all_commands()
                self.motor2.kill_all_commands()

        return True, "Killing all active commands on motor {}".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('value', default=0, type=float)
    @ocs_agent.param('verbose', default=True, type=bool)
    def set_encoder_value(self, session, params):
        """set_encoder_value(motor=1, value=0)

        **Task** - Set the encoder values of given motor(s) to one specified
        value in order to keep track of absolute position.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            value (float): Sets encoder value. (default 0)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(1, job=f"set_encoder_value_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f'Could not set_encoder_value because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if params['motor'] == 1:
                e_positions = self.motor1.set_encoder_value(params['value'])
            elif params['motor'] == 2:
                e_positions = self.motor2.set_encoder_value(params['value'])
            else:
                e_positions = [self.motor1.set_encoder_value(params['value']), self.motor2.set_encoder_value(params['value'])]

        return True, "Setting encoder position of motor {} to {}".format(params['motor'], e_positions)

    @ocs_agent.param('motor', default=3, type=int)
    def get_encoder_value(self, session, params):
        """get_encoder_value(motor=3)

        **Task** - Retrieve all motor step counts to verify movement.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"get_encoder_info_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_encoder_info because lock held by {self.lock.job}')
                return False, 'Could not acquire lock'
            if params['motor'] == 1:
                e_positions = self.motor1.retrieve_encoder_info()
            elif params['motor'] == 2:
                e_positions = self.motor2.retrieve_encoder_info()
            else:
                e_positions = [self.motor1.retrieve_encoder_info(), self.motor2.retrieve_encoder_info()]

        return True, "Current encoder positions: {}".format(
            e_positions)

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    def get_positions(self, session, params):
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

        with self.lock.acquire_timeout(1, job=f"get_positions_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_positions because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['pos_is_inches']:
                if params['motor'] == 1:
                    positions = self.motor1.get_position_in_inches()
                elif params['motor'] == 2:
                    positions = self.motor2.get_position_in_inches()
                else:
                    positions = [self.motor1.get_position_in_inches(), self.motor2.get_position_in_inches()]
            else:
                if params['motor'] == 1:
                    positions = self.motor1.get_position()
                elif params['motor'] == 2:
                    positions = self.motor2.get_position()
                else:
                    positions = [self.motor1.get_position(), self.motor2.get_position()]

        return True, "Current motor positions: {}".format(positions)

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('pos_is_inches', default=True, type=bool)
    def get_immediate_position(self, session, params):
        """get_immediate_position(motor=1, inches=True)

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

        with self.lock.acquire_timeout(1, job=f"get_immediate_position_motor{params['motor']}") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not get_immediate_position because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            if params['motor'] == 1:
                i_positions = self.motor1.get_immediate_position(params['pos_is_inches'])
            elif params['motor'] == 2:
                i_positions = self.motor2.get_immediate_position(params['pos_is_inches'])
            else:
                i_positions = [self.motor1.get_immediate_position(params['pos_is_inches']), self.motor2.get_immediate_position(params['pos_is_inches'])]

        return True, "Current motor positions: {}".format(i_positions)

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def move_off_limit(self, session, params):
        """move_off_limit(motor=3)

        **Task** - Moves motor off limit switch if unexpectedly hit, resetting
        alarms.

        Parameters:
            motor (int): 1,2,3. Determines which motor, either 1 or 2, 3 is for all
                motors. (default 3)
        """

        with self.lock.acquire_timeout(1, job=f"move_off_limit{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not move_off_limit because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.move_off_limit()
            elif params['motor'] == 2:
                self.motor2.move_off_limit()
            else:
                self.motor1.move_off_limit()
                self.motor2.move_off_limit()

        return True, "Motor {} moved off limit switch".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def reset_alarms(self, session, params):
        """reset_alarms(motor=1)

        **Task** - Resets alarm codes present. Only advised if you have checked
        what the alarm is first!

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
        """

        with self.lock.acquire_timeout(1, job=f"reset_alarms_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, "Motors are already moving."
            if not acquired:
                self.log.warn(
                    f"Could not reset_alarms because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.reset_alarms()
            elif params['motor'] == 2:
                self.motor2.reset_alarms()
            else:
                self.motor1.reset_alarms()
                self.motor2.reset_alarms()

        return True, "Alarms reset for motor {}".format(params['motor'])

    @ocs_agent.param('motor', default=1, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    def home_with_limits(self, session, params):
        """home_with_limits(motor=1)

        **Task** - Moves stages to home based on location from limits. One inch
        from the limit switch.

        Parameters:
            motor (int): Determines which motor, either 1 or 2, 3 is for all
                motors. (default 1)
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """

        with self.lock.acquire_timeout(30, job=f"home_with_limits_motor{params['motor']}") as acquired:
            self.move_status = self.movement_check(params)
            if self.move_status:
                return False, 'Motors are moving'
            if not acquired:
                self.log.warn(
                    f"Could not move motor{params['motor']} to home because lock held by {self.lock.job}")
                return False
            if params['motor'] == 1:
                self.motor1.home_with_limits()
            elif params['motor'] == 2:
                self.motor2.home_with_limits()
            else:
                self.motor1.home_with_limits()
                self.move_status = self.motor1.is_moving(params['verbose'])
                while self.move_status:
                    time.sleep(1)
                    self.move_status = self.motor1.is_moving(params['verbose'])
                self.motor2.home_with_limits()

        return True, "Zeroed stages using limit switches"

    @ocs_agent.param('motor', default=3, choices=[1, 2, 3], type=int)
    @ocs_agent.param('verbose', default=True, type=bool)
    @ocs_agent.param('f_sample', default=2, type=float)
    def acq(self, session, params):
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
                (default True)
            f_sample (float): Sampling rate in Hz. (default 2)
        """
        if params is None:
            params = {}
        pm = Pacemaker(params['f_sample'], quantize=True)

        if not self.initialized:
            raise Exception("Motors are not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    "Could not start acq because {} is already running".format(
                        self.lock.job))
                return False, "Could not acquire lock."
            self.log.info(
                f"Starting data acquisition for stages at {params['f_sample']} Hz")
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
                    if mot.mot_id is not None:
                        try:
                            self.log.debug(
                                f"getting position/move status of {mot.mot_id}")
                            # convert move_status to int for C backend reasons...
                            move_status = int(mot.is_moving(params))
                            pos = mot.get_position_in_inches()
                            e_pos = mot.retrieve_encoder_info()
                            data['data'][f'{mot.mot_id}_encoder'] = e_pos[0]
                            data['data'][f'{mot.mot_id}_stepper'] = pos[0]
                            data['data'][f'{mot.mot_id}_connection'] = 1
                            data['data'][f'{mot.mot_id}_move_status'] = move_status

                        except Exception as e:
                            self.log.error(f'error: {e}')
                            self.log.error(
                                f"could not get position/move status of motor{params['motor']}")
                            data['data'][f'{mot.mot_id}_encoder'] = 0
                            data['data'][f'{mot.mot_id}_stepper'] = 0.0
                            data['data'][f'{mot.mot_id}_connection'] = 0
                            data['data'][f'{mot.mot_id}_move_status'] = 0

                self.agent.publish_to_feed('positions', data)
                session.data = data

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """stop_acq(params)

        **Task** - Stop data acquisition.

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
        '--samp',
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
        args.samp)

    agent.register_task('init_motors', m.init_motors)
    agent.register_task('move_axis_to_position', m.move_axis_to_position)
    agent.register_task('move_axis_by_length', m.move_axis_by_length)
    agent.register_task('set_velocity', m.set_velocity)
    agent.register_task('set_acceleration', m.set_acceleration)
    agent.register_task('start_jogging', m.start_jogging)
    agent.register_task('stop_jogging', m.stop_jogging)
    agent.register_task('set_zero', m.set_zero)
    agent.register_task('run_positions', m.run_positions)
    agent.register_task('start_rotation', m.start_rotation)
    agent.register_task('stop_rotation', m.stop_rotation)
    agent.register_task('close_connection', m.close_connection)
    agent.register_task('reconnect_motor', m.reconnect_motor)
    agent.register_task('block_while_moving', m.block_while_moving)
    agent.register_task('kill_all_commands', m.kill_all_commands)
    agent.register_task('set_encoder_value', m.set_encoder_value)
    agent.register_task('get_encoder_value', m.get_encoder_value)
    agent.register_task('get_positions', m.get_positions)
    agent.register_task('is_moving', m.is_moving)
    agent.register_task('get_immediate_position', m.get_immediate_position)
    agent.register_task('move_off_limit', m.move_off_limit)
    agent.register_task('reset_alarms', m.reset_alarms)
    agent.register_task('home_with_limits', m.home_with_limits)
    agent.register_task('set_motor_enable', m.set_motor_enable)
    agent.register_task('motor_reset', m.motor_reset)
    agent.register_task('set_gearing', m.set_gearing)

    agent.register_process('acq', m.acq, m._stop_acq)

    runner.run(agent, auto_reconnect=True)
