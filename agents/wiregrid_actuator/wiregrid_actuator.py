import argparse
import time

from ocs import ocs_agent
from ocs import site_config
from ocs.ocs_twisted import TimeoutLock

# import classes / configs
from src.Actuator import Actuator
import limitswitch_config
import stopper_config


class WiregridActuatorAgent:

    def __init__(self, agent, ip_address='192.168.1.100',
                 interval_time=1, sleep=0.10, verbose=0):
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
            msg = 'Failed to initialize Actuator instance! \
                | Exception: {}'.format(e)
            self.log.warn(msg)
            self.actuator = None

    ######################
    # Internal functions #
    ######################
    # Return: status(True or False), message
    # If an error occurs, return False.

    def _check_connect(self):
        if self.actuator is None:
            msg = 'WARNING: \
                No connection to the actuator (actuator instance is None).'
            self.log.warn(msg)
            return False, msg
        else:
            try:
                self.actuator.check_connect()
            except Exception as e:
                msg = 'WARNING: Failed to check connection with the actuator! \
                    | Exception: {}'.format(e)
                self.log.warn(msg)
                return False, msg
        return True, 'Connection is OK.'

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
            msg = 'WARNING: \
                Failed to initialize Actuator! | Exception: {}'.format(e)
            self.log.warn(msg)
            self.actuator = None
            return False, msg
        # check the connection
        ret, msg = self._check_connect()
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

    # Power off stopper
    def _stopper_off(self):
        try:
            self.actuator.st.set_alloff()
        except Exception as e:
            msg = 'ERROR: Failed to set OFF all the stoppers in set_alloff()! \
                    | Exception: {}'.format(e)
            self.log.error(msg)
            return False, msg
        return True, 'Successfully set OFF all the stoppers!'

    # Return value: True/False, message, limit-switch ON/OFF
    def _forward(self, distance, speedrate=0.1):
        distance = abs(distance)
        LSL2 = 0  # left  actuator outside limit-switch
        LSR2 = 0  # right actuator outside limit-switch
        LSL2, LSR2 = \
            self.actuator.ls.get_onoff(io_name=['LSL2', 'LSR2'])
        if LSL2 == 0 and LSR2 == 0:
            ret, msg = self.actuator.move(distance, speedrate)
            if not ret:
                return False, msg, LSL2 or LSR2
        else:
            self.log.warn(
                'One of inside limit-switches is ON (LSL2={}, LSR2={})!'
                .format(LSL2, LSR2))
            self.log.warn('  --> Did not move.')
        isrun = True
        # Loop until the limit-switch is ON or the actuator moving finishes
        while LSL2 == 0 and LSR2 == 0 and isrun:
            LSL2, LSR2 = \
                self.actuator.ls.get_onoff(io_name=['LSL2', 'LSR2'])
            isrun, msg = self.actuator.isRun()
            if self.verbose > 0:
                self.log.info(
                    'LSL2={}, LSR2={}, run={}'.format(LSL2, LSR2, isrun))
        # Stop the actuator moving
        self.actuator.hold()
        LSonoff = LSL2 or LSR2
        if LSonoff:
            self.log.info(
                'Stopped moving because \
                one of inside limit-switches is ON (LSL2={}, LSR2={})!'
                .format(LSL2, LSR2))
        self.actuator.release()
        return True, \
            'Finish forward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    # Return value: True/False, message, limit-switch ON/OFF
    def _backward(self, distance, speedrate=0.1):
        distance = abs(distance)
        LSL1 = 0  # left  actuator limit-switch @ motor (outside)
        LSR1 = 0  # right actuator limit-switch @ motor (outside)
        LSL1, LSR1 = \
            self.actuator.ls.get_onoff(io_name=['LSL1', 'LSR1'])
        if LSL1 == 0 and LSR1 == 0:
            ret, msg = self.actuator.move(-1*distance, speedrate)
            if not ret:
                return False, msg, LSL1 or LSR1
        else:
            self.log.warn(
                'One of outside limit-switches is ON (LSL1={}, LSR1={})!'
                .format(LSL1, LSR1))
            self.log.warn('  --> Did not move.')
        isrun = True
        # Loop until the limit-switch is ON or the actuator moving finishes
        while LSL1 == 0 and LSR1 == 0 and isrun:
            LSL1, LSR1 = \
                 self.actuator.ls.get_onoff(io_name=['LSL1', 'LSR1'])
            isrun, msg = self.actuator.isRun()
            if self.verbose > 0:
                self.log.info(
                    'LSL1={}, LSR1={}, run={}'.format(LSL1, LSR1, isrun))
        # Stop the actuator moving
        self.actuator.hold()
        LSonoff = LSL1 or LSR1
        if LSonoff:
            self.log.info(
                'Stopped moving because \
                one of outside limit-switches is ON (LSL1={}, LSR1={})!'
                .format(LSL1, LSR1))
        self.actuator.release()
        return True, \
            'Finish backward(distance={}, speedrate={}, limit-switch={})'\
            .format(distance, speedrate, LSonoff), \
            LSonoff

    def _insert(self, main_distance=850, main_speedrate=1.0):
        # Check motor limit-switch
        LSL1, LSR1 = \
            self.actuator.ls.get_onoff(io_name=['LSL1', 'LSR1'])
        # If limit-switch is not ON (The actuator is not at the end.)
        if LSL1 == 0 and LSR1 == 0:
            self.log.warn(
                'The outside limit-switch is NOT ON before inserting.')
            if main_speedrate > 0.1:
                self.log.warn(
                    ' --> Change speedrate: {} --> 0.1'
                    .format(main_speedrate))
                main_speedrate = 0.1
        else:
            self.log.info(
                'The outside limit-switch is ON before inserting.')

        # Check connection
        ret, msg = self._check_connect()
        self.log.info(msg)
        # Reconnect if connection check is failed
        if not ret:
            self.log.warn('Trying to reconnect to the actuator...')
            ret2, msg2 = self._reconnect()
            self.log.warn(msg2)
            if not ret2:
                msg = 'WARNING: Could not connect to \
                    the actuator even after reconnection! --> Stop inserting!'
                self.log.warn(msg)
                return False, msg

        # Release stopper twice (Powering ON the stoppers)
        # 1st trial
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = 'ERROR: Failed to run the stopper set_allon() --> Stop inserting! \
                | Exception: {}'.format(e)
            self.log.error(msg)
            return False, msg
        # 2nd trial (double check)
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = 'ERROR: Failed to run the stopper set_allon() --> Stop inserting! \
                | Exception: {}'.format(e)
            self.log.error(msg)
            return False, msg

        # Initial slow & small forwarding
        ret, msg, LSonoff = self._forward(20, speedrate=0.1)
        # Check the status of the initial forwarding
        if not ret:
            msg = 'ERROR: (In the initail forwarding) {} \
                --> Stop inserting!'.format(msg)
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self._stopper_off()
            return False, msg
        if LSonoff:
            msg = 'WARNING: Limit-switch is ON after the initial forwarding.\
                ---> Stop inserting!'
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            ret, msg2 = self._stopper_off()
            if not ret:
                msg = \
                    'ERROR: (In the initial backwarding) \
                    Failed to lock the actuator by the stopper: {}'\
                    .format(msg2)
                self.log.error(msg)
                return False, msg
            return True, msg
        # Check limit-switch
        LSL1, LSR1 = \
            self.actuator.ls.get_onoff(io_name=['LSL1', 'LSR1'])
        if LSL1 == 1 or LSR1 == 1:
            msg = 'ERROR!: The outside limit-switch is NOT OFF \
                after the initial forwarding. \
                (Maybe the limit-switch is disconnected?) --> Stop inserting!'
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self._stopper_off()
            return False, msg

        # Sleep before the main forwarding
        time.sleep(1)

        # Main forward
        status, msg, LSonoff = \
            self._forward(main_distance, speedrate=main_speedrate)
        if not status:
            msg = 'ERROR!: (In the main forwarding) {} \
                    --> Stop inserting!'.format(msg)
            self.log.error(msg)
            return False, msg
        if LSonoff:
            msg = 'WARNING: Limit-switch is ON after the main forwarding.\
                ---> Stop inserting!'
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            ret, msg2 = self._stopper_off()
            if not ret:
                msg = \
                    'ERROR: (In the main forwarding) \
                    Failed to lock the actuator by the stopper: {}'\
                    .format(msg2)
                return False, msg
            return True, msg

        # Last slow & small forward
        status, msg, LSonoff = self._forward(200, speedrate=0.1)
        if not status:
            msg = 'ERROR!: (In the last forwarding) {}'.format(msg)
            self.log.error(msg)
            return False, msg
            return True, msg
        if LSonoff == 0:
            msg = 'ERROR!: \
                The inside limit-switch is NOT ON after _insert().'
            self.log.error(msg)
            return False, msg

        # Lock the actuator by the stoppers
        ret, msg = self._stopper_off()
        if not ret:
            msg = 'ERROR!: Failed to lock the actuator by the stopper\
                after the last forwarding.!'
            self.log.error(msg)
            return False, msg
        # Check the stopper until all the stoppers are OFF (locked)
        for i in range(self.max_check_stopper):
            onoff_st = self.actuator.st.get_onoff()
            if not any(onoff_st):
                break
        if any(onoff_st):
            msg = 'ERROR!: (After the last forwarding) \
                Failed to lock (OFF) all the stoppers'
            self.log.error(msg)
            return False, msg

        return True, 'Successfully inserting!'

    def _eject(self, main_distance=850, main_speedrate=1.0):
        # Check motor limit-switch
        LSL2, LSR2 = \
            self.actuator.ls.get_onoff(io_name=['LSL2', 'LSR2'])
        if LSL2 == 0 and LSR2 == 0:
            self.log.warn(
                    'The inside limit-switch is NOT ON before ejecting.')
            if main_speedrate > 0.1:
                self.log.warn(
                    ' --> Change speedrate: {} --> 0.1'
                    .format(main_speedrate))
                main_speedrate = 0.1
        else:
            self.log.info(
                'The inside limit-switch is ON before ejecting.')

        # Check connection
        ret, msg = self._check_connect()
        self.log.info(msg)
        # Reconnect if connection check is failed
        if not ret:
            self.log.warn('Trying to reconnect to the actuator...')
            ret2, msg2 = self._reconnect()
            self.log.warn(msg2)
            if not ret2:
                msg = 'WARNING: Could not connect to \
                    the actuator even after reconnection! --> Stop inserting!'
                self.log.warn(msg)
                return False, msg

        # Release stopper twice (Powering ON the stoppers)
        # 1st trial
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = 'ERROR: Failed to run the stopper set_allon() --> Stop inserting! \
                | Exception: {}'.format(e)
            self.log.error(msg)
            return False, msg
        # 2nd trial (double check)
        try:
            self.actuator.st.set_allon()
        except Exception as e:
            msg = 'ERROR: Failed to run the stopper set_allon() --> Stop inserting! \
                | Exception: {}'.format(e)
            self.log.error(msg)
            return False, msg

        # Initial slow & small backwarding
        ret, msg, LSonoff = self._backward(20, speedrate=0.1)
        # Check the status of the initial backwarding
        if not ret:
            msg = 'ERROR: (In the initail backwarding) {} \
                --> Stop ejecting!'.format(msg)
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self._stopper_off()
            return False, msg
        if LSonoff:
            msg = 'WARNING: Limit-switch is ON after the initial backwarding.\
                ---> Stop ejecting!'
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            ret, msg2 = self._stopper_off()
            if not ret:
                msg = \
                    'ERROR: (In the initial backwarding) \
                    Failed to lock the actuator by the stopper: {}'\
                    .format(msg2)
                return False, msg
            return True, msg

        # Check limit-switch
        LSL2, LSR2 = \
            self.actuator.ls.get_onoff(io_name=['LSL2', 'LSR2'])
        if LSL2 == 1 or LSR2 == 1:
            msg = 'ERROR!: The inside limit-switch is NOT OFF \
                after the initial backwarding. \
                (Maybe the limit-switch is disconnected?) --> Stop ejecting!'
            self.log.error(msg)
            # Lock the actuator by the stoppers
            self._stopper_off()
            return False, msg

        # Sleep before the main backwarding
        time.sleep(1)

        # Main backward
        status, msg, LSonoff = \
            self._backward(main_distance, speedrate=main_speedrate)
        if not status:
            msg = 'ERROR!: (In the main backwarding) {} \
                    --> Stop ejecting!'.format(msg)
            self.log.error(msg)
            return False, msg
        if LSonoff:
            msg = 'WARNING: Limit-switch is ON after the main backwarding.\
                ---> Stop ejectting!'
            self.log.warn(msg)
            # Lock the actuator by the stoppers
            ret, msg2 = self._stopper_off()
            if not ret:
                msg = \
                    'ERROR: (In the main backwarding) \
                    Failed to lock the actuator by the stopper: {}'\
                    .format(msg2)
                return False, msg
            return True, msg

        # Last slow & small backward
        status, msg, LSonoff = self._backward(200, speedrate=0.1)
        if not status:
            msg = 'ERROR!: (In the last backwarding) {}'.format(msg)
            self.log.error(msg)
            return False, msg
        if LSonoff == 0:
            msg = 'ERROR!: \
                The outside limit-switch is NOT ON after _eject().'
            self.log.error(msg)
            return False, msg

        # Lock the actuator by the stoppers
        ret, msg = self._stopper_off()
        if not ret:
            msg = 'ERROR!: Failed to lock the actuator by the stopper\
                after the last backwarding.!'
            self.log.error(msg)
            return False, msg
        # Check the stopper until all the stoppers are OFF (released)
        for i in range(self.max_check_stopper):
            onoff_st = self.actuator.st.get_onoff()
            if not any(onoff_st):
                break
        if any(onoff_st):
            msg = 'ERROR!: (After the last backwarding) \
                Failed to lock (OFF) all the stoppers'
            self.log.error(msg)
            return False, msg

        return True, 'Successfully ejecting!'

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
            ret, msg = self._insert(850, 1.0)
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
            ret, msg = self._eject(850, 1.0)
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
                msg = 'ERROR!: Failed insert_homing()\
                    in _insert(1000,0.1): {}'.format(msg)
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
                msg = 'ERROR!: Failed eject_homing()\
                    in _eject(1000,0.1): {}'.format(msg)
                self.log.error(msg)
                raise
            return True, 'Successfully finish eject_homing()!'

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
                {limitswitch:
                    [0 or 1, (0: OFF, 1:ON)
                     0 or 1, (0: OFF, 1:ON)
                     .
                     .
                     ],
                 stopper:
                    [0 or 1, (0: OFF, 1:ON)
                     0 or 1, (0: OFF, 1:ON)
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
            if not acquired:
                self.log.warn(
                    'Lock could not be acquired because it is held by {}.'
                    .format(self.lock.job))
                return False, 'Could not acquire lock in start_acq().'

        session.set_status('running')

        self.run_acq = True
        session.data = {'fields': {}}
        while self.run_acq:
            last_release = time.time()
            self.run_acq = True
            while self.run_acq:
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=120):
                        self.log.warn(
                            'Could not re-acquire lock now held by {}.'
                            .format(self.lock.job))
                        return False, 'Could not re-acquire lock (timeout)'

                current_time = time.time()
                data = {'timestamp': current_time,
                        'block_name': 'actuator_onoff',
                        'data': {}}

                # Take data
                onoff_dict_ls = {}
                onoff_dict_st = {}
                # Get onoff
                onoff_ls = self.actuator.ls.get_onoff()
                onoff_st = self.actuator.st.get_onoff()
                # Data for limitswitch
                for onoff, name in zip(onoff_ls, self.actuator.ls.io_names):
                    data['data']['limitswitch_{}'.format(name)] = onoff
                    onoff_dict_ls[name] = onoff
                # Data for stopper
                for onoff, name in zip(onoff_st, self.actuator.st.io_names):
                    data['data']['stopper_{}'.format(name)] = onoff
                    onoff_dict_st[name] = onoff
                # publish data
                self.agent.publish_to_feed('WGActuator', data)
                # store session.data
                field_dict = {'limitswitch': onoff_dict_ls,
                              'stopper': onoff_dict_st}
                session.data['timestamp'] = current_time
                session.data['fields'] = field_dict

                # wait an interval
                time.sleep(interval_time)

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
                        type=float, default=1,
                        help='Interval time for data taking')
    pgroup.add_argument('--ip-address', dest='ip_address',
                        type=str, default='192.168.1.100',
                        help='IP address of the actuator controller')
    pgroup.add_argument('--sleep', dest='sleep',
                        type=float, default=0.10,
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
        agent_class='WiregridActuatorAgent', parser=parser)

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
    agent.register_task('stop', actuator_agent.stop)
    agent.register_task('release', actuator_agent.release)
    agent.register_process('acq', actuator_agent.start_acq,
                           actuator_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
