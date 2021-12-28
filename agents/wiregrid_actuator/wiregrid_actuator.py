import os
import sys
import argparse
import time

from ocs import ocs_agent
from ocs import site_config
from ocs.ocs_twisted import TimeoutLock

# add PATH to ./src directory
this_dir = os.path.dirname(__file__)
sys.path.append(os.path.join(this_dir, 'src'))

# import classes / configs
from src.Actuator import Actuator
import limitswitch_config
import stopper_config


class WiregridActuatorAgent:

    def __init__(self, agent, ip_address='192.168.1.100',
                 interval_time=1, sleep=0.05, verbose=0):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.run_acq = False
        self.ip_address = ip_address
        self.interval_time = interval_time
        self.sleep = sleep
        self.max_check_stopper = 100
        self.verbose = verbose

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
                'WGActuator', record=True, agg_params=agg_params)

        try:
            self.actuator = Actuator(
                self.ip_address, sleep=self.sleep,
                ls_list=limitswitch_config.IO_INFO,
                st_list=stopper_config.IO_INFO,
                verbose=self.verbose)
        except Exception as e:
            msg = 'Failed to initialize Actuator instance! '\
                  '| Exception: {}'.format(e)
            self.log.warn(msg)
            self.actuator = None

    ######################
    # Internal functions #
    ######################
    # Return: status(True or False), message
    # If an error occurs, return False.

    def _reconnect(self):
        self.log.warn('*** Trying to reconnect... ***')
        # reconnect
        try:
            if self.actuator:
                del self.actuator
            self.actuator = Actuator(
                self.ip_address, sleep=self.sleep,
                ls_list=limitswitch_config.IO_INFO,
                st_list=stopper_config.IO_INFO,
                verbose=self.verbose)
        except Exception as e:
            msg = 'WARNING: '\
                  'Failed to initialize Actuator! | Exception: {}'.format(e)
            self.log.warn(msg)
            self.actuator = None
            return False, msg
        # check the connection
        ret, msg = self.actuator.check_connect()
        if ret:
            msg = 'Successfully reconnected to the actuator!'
            self.log.info(msg)
            return True, msg
        else:
            msg = 'WARNING: Failed to reconnect to the actuator!'
            self.log.warn(msg)
            if self.actuator:
                del self.actuator
            self.actuator = None
            return False, msg

    # Return value: True/False, message, limit-switch ON/OFF
    def _move(self, distance, speedrate, LSLname, LSRname, LSlabel):
        LSL = 0  # left  actuator limit-switch
        LSR = 0  # right actuator limit-switch
        LSL, LSR = \
            self.actuator.ls.get_onoff(io_name=[LSLname, LSRname])
        if LSL == 0 and LSR == 0:
            ret, msg = self.actuator.move(distance, speedrate)
            if not ret:
                return False, msg, LSL or LSR
        else:
            self.log.warn(
                '_move(): One of {} limit-switches is ON (LSL={}, LSR={})!'
                .format(LSlabel, LSL, LSR))
            self.log.warn('  --> Did not move.')
        isrun = True
        # Loop until the limit-switch is ON or the actuator moving finishes
        while LSL == 0 and LSR == 0 and isrun:
            LSL, LSR = \
                self.actuator.ls.get_onoff(io_name=[LSLname, LSRname])
            status, isrun = self.actuator.is_run()
            if self.verbose > 0:
                self.log.info(
                    '_move(): LSL={}, LSR={}, run={}'.format(LSL, LSR, isrun))
        # Stop the actuator moving
        self.actuator.hold()
        LSonoff = LSL or LSR
        if LSonoff:
            self.log.info(
                '_move(): Stopped moving because '
                'one of {} limit-switches is ON (LSL1={}, LSR1={})!'
                .format(LSlabel, LSL, LSR))
        self.actuator.release()
        return True, \
            '_move(): Finish move(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    # Return value: True/False, message, limit-switch ON/OFF
    def _forward(self, distance, speedrate=0.2):
        if distance < 0.:
            distance = abs(distance)
        ret, msg, LSonoff = self._move(
            distance, speedrate, 'LSL1', 'LSR1', 'inside')
        return ret, \
            'Finish forward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    # Return value: True/False, message, limit-switch ON/OFF
    def _backward(self, distance, speedrate=0.2):
        if distance > 0.:
            distance = -1.*abs(distance)
        ret, msg, LSonoff = self._move(
            distance, speedrate, 'LSL2', 'LSR2', 'outside')
        return ret, \
            'Finish backward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    def _insert_eject(
            self, main_distance=800, main_speedrate=1.0, is_insert=True):
        # Function label
        flabel = 'insert' if is_insert else 'eject'
        initial_ls_names = ['LSL2', 'LSR2'] if is_insert else ['LSL1', 'LSR1']
        move_func = self._forward if is_insert else self._backward

        # Check connection
        ret, msg = self.actuator.check_connect()
        self.log.info(msg)

        # Release stopper twice (Powering ON the stoppers)
        # 1st trial
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = '_insert_eject()[{}]: '\
                  'ERROR: Failed to run the stopper set_allon() '\
                  '--> Stop moving! | Exception: {}'.format(flabel, e)
            self.log.error(msg)
            return False, msg
        # 2nd trial (double check)
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = '_insert_eject()[{}]: '\
                  'ERROR: Failed to run the stopper set_allon() '\
                  '--> Stop moving! | Exception: {}'.format(flabel, e)
            self.log.error(msg)
            return False, msg

        # Initial slow & small moving
        ret, msg, LSonoff = move_func(5, speedrate=0.2)
        # Check the status of the initial moving
        if not ret:
            msg = '_insert_eject()[{}]: ERROR: (In the initail moving) {} '\
                  '--> Stop moving!'.format(flabel, msg)
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return False, msg
        if LSonoff:
            msg = '_insert_eject()[{}]: WARNING: '\
                  'Limit-switch is ON after the initial moving. '\
                  '---> Stop moving!'
            self.log.warn(flabel, msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return True, msg
        # Check limit-switch
        LSL, LSR = \
            self.actuator.ls.get_onoff(io_name=initial_ls_names)
        if LSL == 1 or LSR == 1:
            msg = '_insert_eject()[{}]: ERROR!: '\
                  'The limit-switch is NOT OFF '\
                  'after the initial moving. '\
                  '(Maybe the limit-switch is disconnected?) '\
                  '--> Stop moving!'.format(flabel)
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return False, msg

        # Sleep before the main forwarding
        time.sleep(1)

        # Main moving
        status, msg, LSonoff = \
            move_func(main_distance, speedrate=main_speedrate)
        if not status:
            msg = '_insert_eject()[{}]: ERROR!: '\
                  '(In the main moving) {} '\
                  '--> Stop moving!'.format(flabel, msg)
            self.log.error(msg)
            return False, msg
        if LSonoff:
            msg = '_insert_eject()[{}]: WARNING: '\
                  'Limit-switch is ON after the main moving. '\
                  '---> Stop moving!'.format(flabel)
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return True, msg

        # Last slow & small moving
        status, msg, LSonoff = move_func(200, speedrate=0.2)
        if not status:
            msg = '_insert_eject()[{}]: ERROR!: (In the last moving) {}'\
                  .format(flabel, msg)
            self.log.error(msg)
            return False, msg
        if LSonoff == 0:
            msg = '_insert_eject()[{}]: ERROR!: '\
                  'The limit-switch is NOT ON after last moving.'\
                  .format(flabel)
            self.log.error(msg)
            return False, msg

        # Lock the actuator by the stoppers
        self.actuator.st.set_alloff()
        # Check the stopper until all the stoppers are OFF (locked)
        for i in range(self.max_check_stopper):
            onoff_st = self.actuator.st.get_onoff()
            if not any(onoff_st):
                break
        if any(onoff_st):
            msg = 'ERROR!: (After the last moving) '\
                  'Failed to lock (OFF) all the stoppers'
            self.log.error(msg)
            return False, msg

        return True, 'Successfully inserting!'

    def _insert(self, main_distance=800, main_speedrate=1.0):
        ret, msg = self._insert_eject(
            main_distance=main_distance, main_speedrate=main_speedrate,
            is_insert=True)
        return ret, msg

    def _eject(self, main_distance=800, main_speedrate=1.0):
        if main_distance > 0.:
            main_distance = -1. * abs(main_distance)
        ret, msg = self._insert_eject(
            main_distance=main_distance, main_speedrate=main_speedrate,
            is_insert=False)
        return ret, msg

    ##################
    # Main functions #
    ##################
    # Return: status(True or False), message
    # If an error occurs, raise an error

    def check_limitswitch(self, session, params=None):
        """
        Print limit-switch ON/OFF

        Parameters:
            io_name (string): An io name to be printed
                - io_name is determined in limitswitch_config.py
                - If io_name is None, all limit-switches are printed.
        """
        if params is None:
            params = {}
        io_name = params.get('io_name', None)
        onoffs = []
        msg = ''
        with self.lock.acquire_timeout(timeout=3, job='check_limitswitch') \
                as acquired:
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in check_limitswitch().'

            onoffs = self.actuator.ls.get_onoff(io_name)
            io_names = self.actuator.ls.get_io_name(io_name)
            io_labels = self.actuator.ls.get_label(io_name)
            for i, io_name in enumerate(io_names):
                io_label = io_labels[i]
                msg += '{:10s} ({:20s}) : {}\n'\
                    .format(io_name, io_label, 'ON' if onoffs[i] else 'OFF')
            self.log.info(msg)
            return onoffs, msg

    def check_stopper(self, session, params=None):
        """
        Print stopper ON/OFF (ON: lock the actuator, OFF: release the actuator)

        Parameters:
            io_name (string): An io name to be printed
                - io_name is determined in stopper_config.py
                - If io_name is None, all stoppers are printed.
        """
        if params is None:
            params = {}
        io_name = params.get('io_name', None)
        onoffs = []
        msg = ''
        with self.lock.acquire_timeout(timeout=3, job='check_stopper') \
                as acquired:
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in check_stopper().'

            onoffs = self.actuator.st.get_onoff(io_name)
            io_names = self.actuator.st.get_io_name(io_name)
            io_labels = self.actuator.st.get_label(io_name)
            for i, io_name in enumerate(io_names):
                io_label = io_labels[i]
                msg += '{:10s} ({:20s}) : {}\n'\
                    .format(io_name, io_label, 'ON' if onoffs[i] else 'OFF')
            self.log.info(msg)
            return onoffs, msg

    def insert(self, session, params=None):
        """
        Insert the wire-grid into the forebaffle interface above the SAT

        Parameters:
            Nothing
        """
        with self.lock.acquire_timeout(timeout=3, job='insert') as acquired:
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in insert().'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._insert(920, 1.0)
            if not ret:
                msg = 'ERROR!: Failed insert() in _insert(850,1.0): {}'\
                    .format(msg)
                self.log.error(msg)
                raise
            return True, 'Successfully finish insert()!'

    def eject(self, session, params=None):
        """
        Eject the wire-grid from the forebaffle interface above the SAT

        Parameters:
            Nothing
        """
        with self.lock.acquire_timeout(timeout=3, job='eject') as acquired:
            if not acquired:
                self.log.warn(
                        'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'Could not acquire lock in eject().'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._eject(920, 1.0)
            if not ret:
                msg = 'ERROR!: Failed eject() in _eject(850,1.0): {}'\
                    .format(msg)
                self.log.error(msg)
                raise
            return True, 'Successfully finish eject()!'

    def insert_homing(self, session, params=None):
        """
        Insert slowly the wire-grid into the forebaffle interface above the SAT
        until the inside limit-switch becomes ON

        Parameters:
            Nothing
        """
        with self.lock.acquire_timeout(timeout=3, job='insert_homing')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in insert_homing().'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._insert(1000, 0.1)
            if not ret:
                msg = 'ERROR!: Failed insert_homing() '\
                      'in _insert(1000,0.1): {}'.format(msg)
                self.log.error(msg)
                raise
            return True, 'Successfully finish insert_homing()!'

    def eject_homing(self, session, params=None):
        """
        Eject slowly the wire-grid from the forebaffle interface above the SAT
        until the outside limit-switch becomes ON

        Parameters:
            Nothing
        """
        with self.lock.acquire_timeout(timeout=3, job='eject_homing')\
                as acquired:
            if not acquired:
                self.log.warn(
                        'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'Could not acquire lock in eject_homing().'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._eject(1000, 0.1)
            if not ret:
                msg = 'ERROR!: Failed eject_homing() '\
                      'in _eject(1000,0.1): {}'.format(msg)
                self.log.error(msg)
                raise
            return True, 'Successfully finish eject_homing()!'

    def insert_test(self, session, params=None):
        """
        Insert slowly the wire-grid into the forebaffle interface above the SAT
        with a small distance

        Parameters:
            distance:  Actuator moving distance [mm] (default: 10)
            speedrate: Actuator speed rate [0.0, 1.0] (default: 0.1)
        """
        # Get parameters
        if params is None:
            params = {}
        distance = params.get('distance', 10)
        speedrate = params.get('speedrate', 10)
        self.log.info('insert_test(): set distance   = {} mm'
                      .format(distance))
        self.log.info('insert_test(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='insert_test') \
             as acquired:
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in insert_test().'
            # Wait for a second before moving
            time.sleep(1)
            # Release the stoppers
            try:
                self.actuator.st.set_allon()
            except Exception as e:
                msg = 'ERROR: Failed to run the stopper set_allon() '\
                      '--> Stop inserting! | Exception: {}'.format(e)
                self.log.error(msg)
                return False, msg
            # Moving commands
            ret, msg, LSonoff = self._forward(distance, speedrate=speedrate)
            if not ret:
                msg = 'ERROR!: Failed insert_test() in _forward(10,1.): {}'\
                    .format(msg)
                self.log.error(msg)
                raise
            # Lock the stoppers
            self.actuator.st.set_alloff()
            return True, 'Successfully finish insert_test()!'

    def eject_test(self, session, params=None):
        """
        Eject slowly the wire-grid from the forebaffle interface above the SAT
        with a small distance

        Parameters:
            distance:  Actuator moving distance [mm] (default: 10)
            speedrate: Actuator speed rate [0.0, 1.0] (default: 0.1)
        """
        # Get parameters
        if params is None:
            params = {}
        distance = params.get('distance', 10)
        speedrate = params.get('speedrate', 10)
        self.log.info('insert_test(): set distance   = {} mm'
                      .format(distance))
        self.log.info('insert_test(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='eject_test')\
                as acquired:
            if not acquired:
                self.log.warn(
                        'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'Could not acquire lock in eject_test().'
            # Wait for a second before moving
            time.sleep(1)
            # Release the stoppers
            try:
                self.actuator.st.set_allon()
            except Exception as e:
                msg = 'ERROR: Failed to run the stopper set_allon() '\
                      '--> Stop inserting! | Exception: {}'.format(e)
                self.log.error(msg)
                return False, msg
            # Moving commands
            ret, msg, LSonoff = self._backward(distance, speedrate=speedrate)
            if not ret:
                msg = 'ERROR!: Failed eject_test() '\
                      'in _backward(10,1.): {}'.format(msg)
                self.log.error(msg)
                raise
            # Lock the stoppers
            self.actuator.st.set_alloff()
            return True, 'Successfully finish eject_test()!'

    def stop(self, session, params=None):
        """
        Emergency stop of the wire-grid actuator (Disable the actuator moving)
        - This command can be excuted even if the other command is running.

        Parameters:
            Nothing
        """
        self.log.warn('Try to stop and hold the actuator.')
        # This will disable move() command in Actuator class
        # until self.actuator.release() is called.
        ret, msg = self.actuator.hold()
        if not ret:
            msg = 'ERROR!: Failed to hold the actuator: {}'.format(msg)
            self.log.error(msg)
            raise
        return True, 'Successfully finish stop()!'

    def release(self, session, params=None):
        """
        Enable the actuator moving

        Parameters:
            Nothing
        """
        with self.lock.acquire_timeout(timeout=3, job='release')\
                as acquired:
            if not acquired:
                self.log.warn(
                        'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'Could not acquire lock in release().'
            self.log.warn('Try to release the actuator.')
            # This will enable move() command in Actuator class.
            try:
                self.actuator.release()
            except Exception as e:
                msg = 'ERROR!: Failed to release the actuator: {}'.format(e)
                self.log.error(msg)
                raise
            return True, 'Successfully finish release()!'

    def start_acq(self, session, params=None):
        """
        Method to start data acquisition process.

        The most recent data collected is stored in session.data in the
        structure::

            >>> session.data
            {"fields":
                {
                 motor:
                    0 or 1
                 limitswitch:
                 {   LSR1: 0 or 1, (0: OFF, 1:ON)
                     LSR2: 0 or 1, (0: OFF, 1:ON)
                     .
                     .
                     },
                 stopper:
                 {   STR1: 0 or 1, (0: OFF, 1:ON)
                     STR2: 0 or 1, (0: OFF, 1:ON)
                     .
                     .
                     ]
                }
            }

        Parameters:
           Nothing
        """
        if params is None:
            params = {}
        # Define data taking interval_time
        interval_time = params.get('interval-time', None)
        # If interval-time is None, use value passed to Agent init
        if interval_time is None:
            self.log.info(
                'Not set by parameter of "interval-time" for start_acq()')
            interval_time = self.interval_time
        else:
            try:
                interval_time = float(interval_time)
            except ValueError as e:
                self.log.warn(
                    'Parameter of "interval-time" is incorrect : {}'.format(e))
                interval_time = self.interval_time
        self.log.info(
            'interval time for acquisition of limit-switch & stopper = {} sec'
            .format(interval_time))

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            self.log.info('Start to take data')
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in start_acq().'
            self.log.info('Got the lock')

            session.set_status('running')

            self.run_acq = True
            last_release = time.time()
            session.data = {'fields': {}}
            while self.run_acq:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=600):
                        self.log.warn(
                            'Could not re-acquire lock now held by {}.'
                            .format(self.lock.job))
                        return False, 'Could not re-acquire lock (timeout)'

                current_time = time.time()
                data = {'timestamp': current_time,
                        'block_name': 'actuator_onoff',
                        'data': {}}

                # Take data
                onoff_mt = None
                onoff_dict_ls = {}
                onoff_dict_st = {}
                # Get onoff
                onoff_mt = self.actuator.get_motor_onoff()
                onoff_ls = self.actuator.ls.get_onoff()
                onoff_st = self.actuator.st.get_onoff()
                # Data for motor
                data['data']['motor'] = onoff_mt
                # Data for limitswitch
                for onoff, name in \
                        zip(onoff_ls, self.actuator.ls.io_names):
                    data['data']['limitswitch_{}'.format(name)] = onoff
                    onoff_dict_ls[name] = onoff
                # Data for stopper
                for onoff, name in \
                        zip(onoff_st, self.actuator.st.io_names):
                    data['data']['stopper_{}'.format(name)] = onoff
                    onoff_dict_st[name] = onoff
                # publish data
                self.agent.publish_to_feed('WGActuator', data)
                # store session.data
                field_dict = {'motor': onoff_mt,
                              'limitswitch': onoff_dict_ls,
                              'stopper': onoff_dict_st}
                session.data['timestamp'] = current_time
                session.data['fields'] = field_dict

                # wait an interval
                time.sleep(interval_time)
        # End of lock acquire

        self.agent.feeds['WGActuator'].flush_buffer()
        return True, 'Acquisition exited cleanly'

    def stop_acq(self, session, params=None):
        if self.run_acq:
            self.run_acq = False
            session.set_status('stopping')
            return True, 'Stop data acquisition'
        session.set_status('??????')
        return False, 'acq is not currently running'

    # End of class WiregridActuatorAgent


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--interval-time', dest='interval_time',
                        type=float, default=1.,
                        help='Interval time for data taking')
    pgroup.add_argument('--ip-address', dest='ip_address',
                        type=str, default='192.168.1.100',
                        help='IP address of the actuator controller')
    pgroup.add_argument('--sleep', dest='sleep',
                        type=float, default=0.05,
                        help='Sleep time for every actuator command')
    pgroup.add_argument('--verbose', dest='verbose',
                        type=int, default=0,
                        help='Verbosity level')
    return parser


if __name__ == '__main__':
    # site_parser = site_config.add_arguments()
    # if parser is None: parser = argparse.ArgumentParser()
    # parser = make_parser(site_parser)

    # args = parser.parse_args()

    # site_config.reparse_args(args, 'WiregridActuatorAgent')
    # agent, runner = ocs_agent.init_site_agent(args)

    parser = make_parser()
    args = site_config.parse_args(
        agent_class='WGActuatorAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    actuator_agent = WiregridActuatorAgent(
        agent, ip_address=args.ip_address, interval_time=args.interval_time,
        sleep=args.sleep, verbose=args.verbose)

    agent.register_task('check_limitswitch', actuator_agent.check_limitswitch)
    agent.register_task('check_stopper', actuator_agent.check_stopper)
    agent.register_task('insert', actuator_agent.insert)
    agent.register_task('eject', actuator_agent.eject)
    agent.register_task('insert_homing', actuator_agent.insert_homing)
    agent.register_task('eject_homing', actuator_agent.eject_homing)
    agent.register_task('insert_test', actuator_agent.insert_test)
    agent.register_task('eject_test', actuator_agent.eject_test)
    agent.register_task('stop', actuator_agent.stop)
    agent.register_task('release', actuator_agent.release)
    agent.register_process('acq', actuator_agent.start_acq,
                           actuator_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
