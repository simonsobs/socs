import time
import os
from asyncio.timeouts import timeout
import txaio
import argparse

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock, Pacemaker

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from pgrid_motor_driver import Motor

DFLT_VEL = 12
MIN_VEL = 0.25
MAX_VEL = 50

DFLT_ACC = 1
MIN_ACC = 1
MAX_ACC = 3000

class PgridMotorAgent:
    """
    Agent for connecting to the SAT1 polarizing grid rotator motor. 
    Differs from LATRt agent in that motors/controllers are seen as arguments.

    Args:
        ip_address (str): the IP address associated with Motor
        port (int): the port address associated with Motor 
        mode (str): set as 'acq' to start data acquisition on initialize
        samp (float): default sampling frequency in Hz

    """
    def __init__(
            self,
            agent,
            ip_address,
            port,
            mode=None,
            samp=2):

        self.job = None

        # Pass these through site config
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.port = port

        self.samp = float(samp)
        self.move_status = False

        self.initialized = False
        self.take_data = False

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

    def init_motor(self, session, params=None):
        """init_motor()

        **Task** - Connect to the polarizing grid motor

        """
        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:  
            if not acquired:
                self.log.warn(
                    "Could not start init because {} is already running".format(
                        self.lock.job))
                return False, "Could not acquire lock."

            self.log.debug("Lock Acquired Connecting to Stages")

            print('establishing serial server with polarizing grid motor!')
            self.motor = Motor(self.ip_address, self.port, mot_id='pgrid_motor')

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Motor Initialized.'

    @ocs_agent.param('verbose', default=True, type=bool)
    def movement_check(self, params):
        """movement_check(verbose=True)

        **Helper Function** - Checks if motor is moving
        Used within tasks to check movement status.

        Parameters:
            verbose (bool): Prints output from motor requests if True.
                (default True)
        Returns:
            status (bool): Movement status, True if motor is moving,
                False if not.
        """
        status = self.motor.is_moving(params['verbose'])
        return status

    @ocs_agent.param('verbose', default=True, type=bool)
    def is_moving(self, session, params):
        """is_moving(verbose=True)

        **Tasks** - Checks if motor is moving

        Parameters:
            verbose (bool): Prints output from motor requests if True.
                (default True)
        """
        with self.lock.acquire_timeout(1, job="is_moving_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not check because lock held by {self.lock.job}")
                return False
            self.move_status = self.movement_check(params)

        if self.move_status:
            return True, ("Motor is moving.", self.move_status)
        else:
            return False, ("Motor is not moving.", self.move_status)

    @ocs_agent.param('rot_vel', default=DFLT_VEL, type=float, check=lambda x: MIN_VEL <= x <= MAX_VEL)
    @ocs_agent.param('rot_accel', default=DFLT_ACC, type=float, check=lambda x: MIN_ACC <= x <= MAX_ACC)
    def start_rotation(self, session, params):
        """start_rotation(rot_vel=12.0, rot_accel=1.0)

        **Task** - Start rotating motor of polarizer.

        Parameters:
            rot_vel (float): The rotation velocity in revolutions per second
                within range [0.25,50]. (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000]. (default 1.0)
        """

        with self.lock.acquire_timeout(1, job="start_rotation_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not start_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.motor.start_rotation(params['rot_vel'], params['rot_accel'])

        return True, "Started rotating motor at velocity {} and acceleration {}".format(
            params['rot_vel'], params['rot_accel'])

    def stop_rotation(self, session, params=None):
        """stop_rotation()

        **Task** - Stop rotating motor of polarizer.
        """

        with self.lock.acquire_timeout(1, job="stop_rotation_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not stop_rotation because lock held by {self.lock.job}")
                return False, "Could not acquire lock"
            
            self.motor.stop_rotation()

        return True, "Stopped rotating motor"

    @ocs_agent.param('rot_vel', default=DFLT_VEL, type=float, check=lambda x: MIN_VEL <= x <= MAX_VEL)
    def set_rot_vel(self, session, params):
        """set_rot_vel(rot_vel=0.25)

        **Task** - Set rotational velocity of polarizing grid motor while already in motion

        Parameters:
            rot_vel (float): Sets rotational velocity of motor in revolutions per second
                within range [0.25,50]. (default 12.0)
        """

        with self.lock.acquire_timeout(timeout=1, job='set_rot_vel_pgrid_motor') as acquired:
            self.move_status = self.movement_check(params)
            if not self.move_status:
                return False, "Motor is not moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_rot_vel because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.motor.set_rot_vel(params['rot_vel'])
            
        return True, "Set rotational velocity of pgrid_motor to {}".format(params['rot_vel'])

    def get_rot_vel(self, session, params=None):
        """get_rot_vel()

        **Task** - Get the rotational velocity of polarizing grid motor

        Returns:
            rot_vel (float): the rotational velocity of polarizing grid motor in revolutions per second
        """

        with self.lock.acquire_timeout(timeout=1, job='get_rot_vel_pgrid_motor') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not get_rot_vel because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            rot_vel = self.motor.get_rot_vel()
            
        return rot_vel, "Rotational velocity of pgrid_motor is {}".format(rot_vel)

    @ocs_agent.param('rot_accel', default=DFLT_ACC, type=float, check=lambda x: MIN_ACC <= x <= MAX_ACC)
    def set_rot_accel(self, session, params):
        """set_rot_accel(rot_accel=1)

        **Task** - Set rotational acceleration of polarizing grid motor.

        Parameters:
            rot_accel (float): Sets rotational acceleration of motor 
                in revolutions per second per second within range [1,3000]. (default 1.0)
        """

        with self.lock.acquire_timeout(timeout=1, job='set_rot_vel_pgrid_motor') as acquired:
            self.move_status = self.movement_check(params)
            if not self.move_status:
                return False, "Motor is not moving."
            if not acquired:
                self.log.warn(
                    f"Could not set_rot_accel because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.motor.set_rot_accel(params['rot_accel'])
            
        return True, "Set rotational acceleration of pgrid_motor to {}".format(params['rot_accel'])

    def get_rot_accel(self, session, params=None):
        """get_rot_accel()

        **Task** - Get the rotational acceleration of polarizing grid motor

        Returns:
            rot_accel (float): the rotational acceleration of polarizing grid motor 
                in revolutions per second per second
        """

        with self.lock.acquire_timeout(timeout=1, job='get_rot_accel_pgrid_motor') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not get_rot_accel because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            accel = self.motor.get_rot_accel()
            
        return accel, "Rotational acceleration of pgrid_motor is {}".format(accel)

    def close_connection(self, session, params=None):
        """close_connection()

        **Task** - Close connection to motor.
        """

        with self.lock.acquire_timeout(1, job="close_connection_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not close connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"

            self.motor.close_connection()

        return True, "Closed connection to pgrid_motor"

    def reconnect_motor(self, session, params=None):
        """reconnect_motor()

        **Task** - Reestablish a connection to motor if connection is lost.
        """
        with self.lock.acquire_timeout(1, job="reconnect_motor_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not reestablish connection because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motor.reconnect_motor()
                
        return True, "Motor reconnection task completed"

    def kill_all_commands(self, session, params=None):
        """kill_all_commands()

        **Task** - Stops all active commands on the device.
        """

        with self.lock.acquire_timeout(1, job="kill_all_commands_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not kill_all_commands because lock held by {self.lock.job}')
                return False, "Could not acquire lock"
            self.motor.kill_all_commands()

        return True, "Killing all active commands on pgrid_motor"

    def reset_alarms(self, session, params=None):
        """reset_alarms()

        **Task** - Resets alarm codes present. Only advised if you have checked
        what the alarm is first!
        """

        with self.lock.acquire_timeout(1, job="reset_alarms_pgrid_motor") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not reset_alarms because lock held by {self.lock.job}")
                return False
            self.motor.reset_alarms()

        return True, "Alarms reset for pgrid_motor"

    @ocs_agent.param('verbose', default=True, type=bool)
    @ocs_agent.param('f_sample', default=2, type=float)
    def acq(self, session, params):
        """start_acq(verbose=False, f_sample=2)

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
            verbose (bool): Prints output from motor requests if True.
                (default True)
            f_sample (float): Sampling rate in Hz. (default 2)
        """
        if params is None:
            params = {}

        pm = Pacemaker(params['f_sample'], quantize=True)

        if not self.initialized:
            raise Exception("Motor is not initialized")

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

                if self.motor.mot_id is not None:
                    try:
                        self.log.debug(
                            f"getting rot_vel/move status of pgrid_motor")
                        move_status = self.motor.is_moving(params)
                        rot_vel = self.motor.get_rot_vel(params)
                        data['data']['grid_motor_rot_vel'] = rot_vel
                        data['data']['pgrid_motor_connection'] = 1
                        data['data']['pgrid_motor_move_status'] = move_status

                    except Exception as e:
                        self.log.error(f'error: {e}')
                        self.log.error(
                            f"could not get rot_vel/move status of pgrid_motor")
                        data['data']['pgrid_motor_rot_vel'] = 0.0
                        data['data']['pgrid_motor_connection'] = 0

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
    pgroup.add_argument('--ip_address', help="MOXA IP address", type=str)
    pgroup.add_argument(
        '--port',
        help="MOXA port number for pgrid_motor",
        type=int)
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
    args = site_config.parse_args(agent_class='PgridMotorAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    m = PgridMotorAgent(
        agent,
        args.ip_address,
        args.port,
        args.mode,
        args.samp)

    agent.register_task('init_motor', m.init_motor)
    agent.register_task('start_rotation', m.start_rotation)
    agent.register_task('stop_rotation', m.stop_rotation)
    agent.register_task('set_rot_vel', m.set_rot_vel)
    agent.register_task('get_rot_vel', m.get_rot_vel)
    agent.register_task('set_rot_accel', m.set_rot_accel)
    agent.register_task('get_rot_accel', m.get_rot_accel)
    agent.register_task('close_connect', m.close_connection)
    agent.register_task('reconnect_motor', m.reconnect_motor)
    agent.register_task('kill_all', m.kill_all_commands)
    agent.register_task('is_moving', m.is_moving)
    agent.register_task('reset_alarm', m.reset_alarms)

    agent.register_process('acq', m.acq, m._stop_acq)

    runner.run(agent, auto_reconnect=True)

