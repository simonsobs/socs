import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

import socs.agents.wiregrid_actuator.limitswitch_config as limitswitch_config
import socs.agents.wiregrid_actuator.stopper_config as stopper_config
from socs.agents.wiregrid_actuator.drivers.Actuator import Actuator


class WiregridActuatorAgent:
    """ Agent to control the linear actuator
    to insert or eject the wire-grid via a GALIL motor controller.
    It communicates with the controller via an ethernet.
    It also reads ON/OFF of the limit-switches on the ends of the actuators
    and lock/unlock the stoppers to lock/unlock the actuators.

    Args:
        ip_address      (str): IP address for the GALIL motor controller
        interval_time (float): Interval time for dat acquisition
        sleep         (float): sleep time for every commands
        the motor controller
    """

    def __init__(self, agent, ip_address='192.168.1.100',
                 interval_time=1., sleep=0.05, verbose=0):
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
            'wgactuator', record=True, agg_params=agg_params)

        try:
            self.actuator = Actuator(
                self.ip_address, sleep=self.sleep,
                ls_list=limitswitch_config.IO_INFO,
                st_list=stopper_config.IO_INFO,
                verbose=self.verbose)
        except Exception as e:
            msg = '__init__(): Failed to initialize Actuator instance! '\
                  '| Exception = "{}"'.format(e)
            self.log.error(msg)
            self.actuator = None
            raise e

    ######################
    # Internal functions #
    ######################
    # Return: status(True or False), message
    # If an error occurs, return False.

    # Return: True/False, message, limit-switch ON/OFF
    def _move(self, distance, speedrate, LSLname, LSRname, LSlabel):
        LSL = 0  # left  actuator limit-switch
        LSR = 0  # right actuator limit-switch
        LSL, LSR = \
            self.actuator.ls.get_onoff(io_name=[LSLname, LSRname])
        if LSL == 0 and LSR == 0:
            ret = self.actuator.move(distance, speedrate)
            if not ret:
                msg = '_move(): WARNING!: Failed to move.'
                self.log.warn(msg)
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
            isrun = self.actuator.is_run()
            if self.verbose > 0:
                self.log.info(
                    '_move(): LSL={}, LSR={}, run={}'.format(LSL, LSR, isrun))
        # Stop the actuator moving
        self.actuator.stop()
        LSonoff = LSL or LSR
        if LSonoff:
            self.log.info(
                '_move(): Stopped moving because '
                'one of {} limit-switches is ON (LSL={}, LSR={})!'
                .format(LSlabel, LSL, LSR))
        return True, \
            '_move(): Finish move(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    # Return value: True/False, message, limit-switch ON/OFF
    def _forward(self, distance, speedrate=0.2):
        if distance < 0.:
            distance = abs(distance)
        ret, msg, LSonoff = self._move(
            distance, speedrate, 'LSL2', 'LSR2', 'inside')
        return ret, \
            '_forward(): '\
            'Finish forward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    # Return value: True/False, message, limit-switch ON/OFF
    def _backward(self, distance, speedrate=0.2):
        if distance > 0.:
            distance = -1. * abs(distance)
        ret, msg, LSonoff = self._move(
            distance, speedrate, 'LSL1', 'LSR1', 'outside')
        return ret, \
            '_backward(): '\
            'Finish backward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    def _insert_eject(
            self, main_distance=920, main_speedrate=1.0, is_insert=True):
        # Function label
        flabel = 'insert' if is_insert else 'eject'
        initial_ls_names = ['LSL1', 'LSR1'] if is_insert else ['LSL2', 'LSR2']
        move_func = self._forward if is_insert else self._backward

        # Check connection
        ret = self.actuator.check_connect()
        if ret:
            if self.verbose > 0:
                self.log.info(
                    '_insert_eject()[{}]: '
                    'the connection to the actuator controller is OK!'
                    .format(flabel))
        else:
            msg = '_insert_eject()[{}]: ERROR!: '\
                  'the connection to the actuator controller is BAD!'\
                  .format(flabel)
            self.log.error(msg)
            return False, msg

        # Release stopper (Powering ON the stoppers)
        # 1st trial
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = '_insert_eject()[{}]: '\
                  'ERROR!: Failed to run the stopper set_allon() '\
                  '--> Stop moving! | Exception = "{}"'.format(flabel, e)
            self.log.error(msg)
            return False, msg
        # Check the stopper
        onoff_st = self.actuator.st.get_onoff()
        if not all(onoff_st):
            # 2nd trial (double check)
            try:
                self.actuator.st.set_allon()
            except Exception as e:
                msg = '_insert_eject()[{}]: '\
                      'ERROR!: Failed to run the stopper set_allon() '\
                      '--> Stop moving! | Exception = "{}"'.format(flabel, e)
                self.log.error(msg)
                return False, msg
            onoff_st = self.actuator.st.get_onoff()
            # Error in powering ON stopper
            if not all(onoff_st):
                msg = '_insert_eject()[{}]: '\
                      'ERROR!: Could not confirm all the stopper released '\
                      'after twice stopper set_allon()! '\
                      '--> Stop moving!'.format(flabel)
                self.log.error(msg)
                return False, msg

        # Initial slow & small moving
        ret, msg, LSonoff = move_func(5, speedrate=0.2)
        # Check the status of the initial moving
        if not ret:
            msg = '_insert_eject()[{}]: ERROR!: in the initail moving | {} '\
                  '--> Stop moving!'.format(flabel, msg)
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return False, msg
        if LSonoff:
            msg = '_insert_eject()[{}]: WARNING!: '\
                  'Limit-switch is ON after the initial moving. '\
                  '---> Stop moving!'.format(flabel)
            self.log.warn(msg)
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
                  'in the main moving | {} '\
                  '--> Stop moving!'.format(flabel, msg)
            self.log.error(msg)
            return False, msg
        if LSonoff:
            msg = '_insert_eject()[{}]: WARNING!: '\
                  'Limit-switch is ON after the main moving. '\
                  '---> Stop moving!'.format(flabel)
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            self.actuator.st.set_alloff()
            return True, msg

        # Last slow & small moving
        status, msg, LSonoff = move_func(200, speedrate=0.2)
        if not status:
            msg = '_insert_eject()[{}]: ERROR!: in the last moving | {}'\
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
            msg = '_insert_eject()[{}]: ERROR!: (After the last moving) '\
                  'Failed to lock (OFF) all the stoppers'.format(flabel)
            self.log.error(msg)
            return False, msg

        return True, '_insert_eject()[{}]: Successfully moving!'.format(flabel)

    def _insert(self, main_distance=920, main_speedrate=1.0):
        ret, msg = self._insert_eject(
            main_distance=main_distance, main_speedrate=main_speedrate,
            is_insert=True)
        return ret, msg

    def _eject(self, main_distance=920, main_speedrate=1.0):
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

    @ocs_agent.param('speedrate', default=1.0, type=float,
                     check=lambda x: 0.0 < x <= 5.0)
    @ocs_agent.param('high_speed', default=False, type=bool)
    def insert(self, session, params=None):
        """insert(speedrate=1.0, high_speed=False)

        **Task** - Insert the wire-grid into the forebaffle interface above the
        SAT.

        Parameters:
            speedrate (float): Actuator speed rate [0.0, 5.0] (default: 1.0)
                DO NOT use ``speedrate > 1.0`` if ``el != 90 deg``!
            high_speed (bool): If False, speedrate is limited to 1.0. Defaults
                to False.
        """
        # Get parameters
        speedrate = params.get('speedrate')
        high_speed = params.get('high_speed')
        if not high_speed:
            speedrate = min(speedrate, 1.0)
        self.log.info('insert(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='insert') as acquired:
            if not acquired:
                self.log.warn(
                    'insert(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'insert(): Could not acquire lock'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._insert(920, speedrate)
            if not ret:
                msg = 'insert(): '\
                      'ERROR!: Failed insert() in _insert(920,{}) | {}'\
                      .format(speedrate, msg)
                self.log.error(msg)
                return False, msg
            return True, 'insert(): Successfully finish!'

    @ocs_agent.param('speedrate', default=1.0, type=float,
                     check=lambda x: 0.0 < x <= 5.0)
    @ocs_agent.param('high_speed', default=False, type=bool)
    def eject(self, session, params=None):
        """eject(speedrate=1.0, high_speed=False)

        **Task** - Eject the wire-grid from the forebaffle interface above the
        SAT.

        Parameters:
            speedrate (float): Actuator speed rate [0.0, 5.0] (default: 1.0)
                DO NOT use ``speedrate > 1.0`` if ``el != 90 deg``!
            high_speed (bool): If False, speedrate is limited to 1.0. Defaults
                to False.
        """
        # Get parameters
        speedrate = params.get('speedrate')
        high_speed = params.get('high_speed')
        if not high_speed:
            speedrate = min(speedrate, 1.0)
        self.log.info('eject(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='eject') as acquired:
            if not acquired:
                self.log.warn(
                    'eject(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'eject(): Could not acquire lock'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._eject(920, speedrate)
            if not ret:
                msg = 'eject(): ERROR!: Failed in _eject(920,{}) | {}'\
                    .format(speedrate, msg)
                self.log.error(msg)
                return False, msg
            return True, 'eject(): Successfully finish!'

    def check_limitswitch(self, session, params=None):
        """check_limitswitch(io_name)

        **Task** - Print limit-switch ON/OFF state.

        Parameters:
            io_name (string): The IO name to be printed. Names configured in
                ``limitswitch_config.py``. If None, all limit-switches are
                printed.
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
                    'check_limitswitch(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, \
                    'check_limitswitch(): '\
                    'Could not acquire lock'

            onoffs = self.actuator.ls.get_onoff(io_name)
            io_names = self.actuator.ls.get_io_name(io_name)
            io_labels = self.actuator.ls.get_label(io_name)
            for i, io_name in enumerate(io_names):
                io_label = io_labels[i]
                msg += 'check_limitswitch(): {:10s} ({:20s}) : {}\n'\
                    .format(io_name, io_label, 'ON' if onoffs[i] else 'OFF')
            self.log.info(msg)
            return True, msg

    def check_stopper(self, session, params=None):
        """check_stopper(io_name)

        **Task** - Print stopper ON/OFF (ON: lock the actuator, OFF: release
        the actuator)

        Parameters:
            io_name (string): The IO name to be printed. Names configured in
                ``stopper_config.py``. If None, all stoppers are printed.
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
                    'check_stopper(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'check_stopper(): Could not acquire lock'

            onoffs = self.actuator.st.get_onoff(io_name)
            io_names = self.actuator.st.get_io_name(io_name)
            io_labels = self.actuator.st.get_label(io_name)
            for i, io_name in enumerate(io_names):
                io_label = io_labels[i]
                msg += 'check_stopper(): {:10s} ({:20s}) : {}\n'\
                    .format(io_name, io_label, 'ON' if onoffs[i] else 'OFF')
            self.log.info(msg)
            return True, msg

    def insert_homing(self, session, params=None):
        """insert_homing()

        **Task** - Insert slowly the wire-grid into the forebaffle interface
        above the SAT until the inside limit-switch becomes ON.

        """
        with self.lock.acquire_timeout(timeout=3, job='insert_homing')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'insert_homing(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'insert_homing(): Could not acquire lock'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._insert(1000, 0.1)
            if not ret:
                msg = 'insert_homing(): ERROR!: Failed '\
                      'in _insert(1000,0.1) | {}'.format(msg)
                self.log.error(msg)
                return False, msg
            return True, 'insert_homing(): Successfully finish!'

    def eject_homing(self, session, params=None):
        """eject_homing()

        **Task** - Eject slowly the wire-grid from the forebaffle interface
        above the SAT until the outside limit-switch becomes ON.

        """
        with self.lock.acquire_timeout(timeout=3, job='eject_homing')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'eject_homing(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'eject_homing(): Could not acquire lock'
            # Wait for a second before moving
            time.sleep(1)
            # Moving commands
            ret, msg = self._eject(1000, 0.1)
            if not ret:
                msg = 'eject_homing(): ERROR!: Failed '\
                      'in _eject(1000,0.1) | {}'.format(msg)
                self.log.error(msg)
                return False, msg
            return True, 'eject_homing(): Successfully finish!'

    @ocs_agent.param('distance', default=10., type=float)
    @ocs_agent.param('speedrate', default=0.2, type=float,
                     check=lambda x: 0.0 < x <= 5.0)
    @ocs_agent.param('high_speed', default=False, type=bool)
    def insert_test(self, session, params):
        """insert_test(distance=10, speedrate=0.2, high_speed=False)

        **Task** - Insert slowly the wire-grid into the forebaffle interface
        above the SAT with a small distance.

        Parameters:
            distance (float): Actuator moving distance [mm] (default: 10)
            speedrate (float): Actuator speed rate [0.0, 5.0] (default: 0.2)
                DO NOT use ``speedrate > 1.0`` if ``el != 90 deg``!
            high_speed (bool): If False, speedrate is limited to 1.0. Defaults
                to False.
        """
        # Get parameters
        distance = params.get('distance')
        speedrate = params.get('speedrate')
        high_speed = params.get('high_speed')
        if not high_speed:
            speedrate = min(speedrate, 1.0)
        self.log.info('insert_test(): set distance   = {} mm'
                      .format(distance))
        self.log.info('insert_test(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='insert_test') \
                as acquired:
            if not acquired:
                self.log.warn(
                    'insert_test(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'insert_test(): Could not acquire lock.'
            # Wait for a second before moving
            time.sleep(1)
            # Release the stoppers
            try:
                self.actuator.st.set_allon()
            except Exception as e:
                msg = 'insert_test(): ERROR!: '\
                      'Failed to run the stopper set_allon() '\
                      '--> Stop inserting! | Exception = "{}"'.format(e)
                self.log.error(msg)
                return False, msg
            # Moving commands
            ret, msg, LSonoff = self._forward(distance, speedrate=speedrate)
            if not ret:
                msg = 'insert_test(): ERROR!: Failed in _forward(10,1.) | {}'\
                    .format(msg)
                self.log.error(msg)
                return False, msg
            # Lock the stoppers
            self.actuator.st.set_alloff()
            return True, 'insert_test(): Successfully finish!'

    @ocs_agent.param('distance', default=10., type=float)
    @ocs_agent.param('speedrate', default=0.2, type=float,
                     check=lambda x: 0.0 < x <= 5.0)
    @ocs_agent.param('high_speed', default=False, type=bool)
    def eject_test(self, session, params):
        """eject_test(distance=10, speedrate=0.2, high_speed=False)

        **Task** - Eject slowly the wire-grid from the forebaffle interface
        above the SAT with a small distance.

        Parameters:
            distance (float): Actuator moving distance [mm] (default: 10)
            speedrate (float): Actuator speed rate [0.0, 5.0] (default: 0.2)
                DO NOT use ``speedrate > 1.0`` if ``el != 90 deg``!
            high_speed (bool): If False, speedrate is limited to 1.0. Defaults
                to False.
        """
        # Get parameters
        distance = params.get('distance', 10)
        speedrate = params.get('speedrate', 0.2)
        high_speed = params.get('high_speed')
        if not high_speed:
            speedrate = min(speedrate, 1.0)
        self.log.info('eject_test(): set distance   = {} mm'
                      .format(distance))
        self.log.info('eject_test(): set speed rate = {}'
                      .format(speedrate))

        with self.lock.acquire_timeout(timeout=3, job='eject_test')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'eject_test(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'eject_test(): Could not acquire lock.'
            # Wait for a second before moving
            time.sleep(1)
            # Release the stoppers
            try:
                self.actuator.st.set_allon()
            except Exception as e:
                msg = 'eject_test(): ERROR!: '\
                      'Failed to run the stopper set_allon() '\
                      '--> Stop ejecting! | Exception = "{}"'.format(e)
                self.log.error(msg)
                return False, msg
            # Moving commands
            ret, msg, LSonoff = self._backward(distance, speedrate=speedrate)
            if not ret:
                msg = 'eject_test(): ERROR!: Failed '\
                      'in _backward(10,1.) | {}'.format(msg)
                self.log.error(msg)
                return False, msg
            # Lock the stoppers
            self.actuator.st.set_alloff()
            return True, 'eject_test(): Successfully finish!'

    def motor_on(self, session, params=None):
        """motor_on()

        **Task** - Power ON the motors of the actuators.

        """
        with self.lock.acquire_timeout(timeout=3, job='motor_on')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'motor_on(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'motor_on(): Could not acquire lock.'
            self.log.warn('motor_on(): Try to power ON the actuator motors.')
            try:
                self.actuator.set_motor_onoff(onoff=True)
            except Exception as e:
                msg = 'motor_on(): ERROR!: '\
                      'Failed to power ON the actuator motors | '\
                      'Exception = "{}"'.format(e)
                self.log.error(msg)
                return False, msg
            return True, 'motor_on(): Successfully finish!'

    def motor_off(self, session, params=None):
        """motor_off()

        **Task** - Power OFF the motors of the actuators.

        """
        with self.lock.acquire_timeout(timeout=3, job='motor_off')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'motor_off(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'motor_off(): Could not acquire lock.'
            self.log.warn('motor_off(): Try to power OFF the actuator motors.')
            try:
                self.actuator.set_motor_onoff(onoff=False)
            except Exception as e:
                msg = 'motor_off(): ERROR!: '\
                      'Failed to power OFF the actuator motors | '\
                      'Exception = "{}"'.format(e)
                self.log.error(msg)
                return False, msg
            return True, 'motor_off(): Successfully finish!'

    def stop(self, session, params=None):
        """stop()

        **Task** - Emergency stop of the wire-grid actuator. (Disable the
        actuator motion.)

        .. note::
            This command can be excuted even if the other command is running.

        """
        self.log.warn('stop(): Try to stop and hold the actuator.')
        # This will disable move() command in Actuator class
        # until self.actuator.release() is called.
        ret = self.actuator.hold()
        if not ret:
            msg = 'stop(): ERROR!: Failed to hold the actuator'
            self.log.error(msg)
            return False, msg
        return True, 'stop(): Successfully finish!'

    def release(self, session, params=None):
        """release()

        **Task** - Enable the actuator moving.

        """
        with self.lock.acquire_timeout(timeout=3, job='release')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'release(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'release(): Could not acquire lock.'
            self.log.warn('release(): Try to release the actuator.')
            # This will enable move() command in Actuator class.
            try:
                self.actuator.release()
            except Exception as e:
                msg = 'release(): ERROR!: '\
                      'Failed to release the actuator | '\
                      'Exception = "{}"'.format(e)
                self.log.error(msg)
                return False, msg
            return True, 'release(): Successfully finish!'

    def reconnect(self, session, params=None):
        """reconnect()

        **Task** - Reconnect to the actuator controller.

        .. warning::
            This command turns OFF the motor power!

        """
        with self.lock.acquire_timeout(timeout=3, job='reconnect')\
                as acquired:
            if not acquired:
                self.log.warn(
                    'reconnect(): '
                    'Lock could not be acquired because it is held by {}.'
                        .format(self.lock.job))
                return False, 'reconnect(): Could not acquire lock.'
            self.log.warn('reconnect(): *** Trying to reconnect... ***')
            # reconnect
            ret = self.actuator.reconnect()
            if not ret:
                msg = 'reconnect(): ERROR!: '\
                      'Failed to reconnect the actuator controller!'
                self.log.warn(msg)
                return False, msg
            # Check connection
            ret = self.actuator.check_connect()
            if ret:
                msg = 'reconnect(): Successfully reconnected to the actuator!'
                self.log.info(msg)
                return True, msg
            else:
                msg = 'reconnect(): ERROR!: '\
                      'Failed to reconnect to the actuator!'
                self.log.error(msg)
                return False, msg

    def acq(self, session, params=None):
        """acq()

        **Process** - Run data acquisition.

        Parameters:
           interval-time: interval time for data acquisition

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {'fields':
                    {
                     'motor':
                        0 or 1
                     'limitswitch':
                     {   'LSR1': 0 or 1, (0: OFF, 1:ON)
                         'LSR2': 0 or 1, (0: OFF, 1:ON)
                         .
                         .
                         },
                     'stopper':
                     {   'STR1': 0 or 1, (0: OFF, 1:ON)
                         'STR2': 0 or 1, (0: OFF, 1:ON)
                         .
                         .
                         },
                     'position':
                        'inside' or 'outside' or 'unknown'
                    },
                 'timestamp':1601925677.6914878
                }
        """
        if params is None:
            params = {}
        # Define data taking interval_time
        interval_time = params.get('interval-time', None)
        # If interval-time is None, use value passed to Agent init
        if interval_time is None:
            self.log.info(
                'acq(): '
                'Not set by parameter of "interval-time" for acq()')
            interval_time = self.interval_time
        else:
            try:
                interval_time = float(interval_time)
            except ValueError as e:
                self.log.warn(
                    'acq(): '
                    'Parameter of "interval-time" is incorrect | '
                    'Exception = "{}"'.format(e))
                interval_time = self.interval_time
        self.log.info(
            'acq(): '
            'interval time for acquisition of limit-switch & stopper = {} sec'
            .format(interval_time))

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            self.log.info('acq(): Start to take data')
            if not acquired:
                self.log.warn(
                    'acq(): '
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'acq(): Could not acquire lock.'
            self.log.info('acq(): Got the lock')

            self.run_acq = True
            last_release = time.time()
            session.data = {'fields': {}}
            while self.run_acq:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=180):
                        self.log.warn(
                            'acq(): '
                            'Could not re-acquire lock now held by {}.'
                            .format(self.lock.job))
                        return False, \
                            'acq(): Could not re-acquire lock (timeout)'

                current_time = time.time()
                data = {'timestamp': current_time,
                        'block_name': 'actuator_onoff',
                        'data': {}}

                # Take data
                onoff_mt = None
                onoff_dict_ls = {}
                onoff_dict_st = {}
                # Get onoff
                try:
                    onoff_mt = self.actuator.get_motor_onoff()
                    onoff_ls = self.actuator.ls.get_onoff()
                    onoff_st = self.actuator.st.get_onoff()
                except Exception as e:
                    msg = 'acq(): '\
                          'ERROR!: Failed to get status '\
                          'from the actuator controller!'\
                          '--> Stop acq()! | Exception = "{}"'.format(e)
                    self.log.error(msg)
                    return False, msg

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
                # Data for position
                if (onoff_dict_ls['LSR1'] == 1 or onoff_dict_ls['LSL1'] == 1) \
                        and not (onoff_dict_ls['LSR2'] == 1 or onoff_dict_ls['LSL2'] == 1):
                    position = 'outside'
                elif (onoff_dict_ls['LSR2'] == 1 or onoff_dict_ls['LSL2'] == 1) \
                        and not (onoff_dict_ls['LSR1'] == 1 or onoff_dict_ls['LSL1'] == 1):
                    position = 'inside'
                else:
                    position = 'unknown'
                    self.log.warn(
                        'acq(): '
                        'Unknown position!')
                data['data']['position'] = position
                # publish data
                self.agent.publish_to_feed('wgactuator', data)
                # store session.data
                field_dict = {'motor': onoff_mt,
                              'limitswitch': onoff_dict_ls,
                              'stopper': onoff_dict_st,
                              'position': position}
                session.data['timestamp'] = current_time
                session.data['fields'] = field_dict

                # wait an interval
                time.sleep(interval_time)
        # End of lock acquire

        self.agent.feeds['wgactuator'].flush_buffer()
        return True, 'acq(): Acquisition exited cleanly'

    def stop_acq(self, session, params=None):
        if self.run_acq:
            self.run_acq = False
            return True, 'stop_acq(): Stop data acquisition'
        return False, 'stop_acq(): acq is not currently running'

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


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='WiregridActuatorAgent',
                                  parser=parser,
                                  args=args)

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
    agent.register_task('motor_on', actuator_agent.motor_on)
    agent.register_task('motor_off', actuator_agent.motor_off)
    agent.register_task('stop', actuator_agent.stop)
    agent.register_task('release', actuator_agent.release)
    agent.register_task('reconnect', actuator_agent.reconnect)
    agent.register_process('acq', actuator_agent.acq,
                           actuator_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
