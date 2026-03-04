# Built-in python modules
import os
import time

# Specific module for actuator controller
on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    import gclib

from socs.agents.wiregrid_actuator.drivers.DigitalIO import DigitalIO


class Actuator:
    """
    The Actuator class is for writing commands and reading status
    of the actuator via the Galil actuator controller.

    Args:
        ip_address(string)  : IP address of the actuator controller
        sleep(float)        : sleep time for every commands
        ls_list(list)       : limit-switch IO configurations
        st_list(list)       : stopper IO configurations
        verbose(int)        : verbosity level
    """

    def __init__(self, ip_address='192.168.1.100', sleep=0.05,
                 ls_list=[], st_list=[], verbose=0):
        self.ip_address = ip_address
        self.sleep = sleep
        self.verbose = verbose

        self.STOP = False  # This will become True in emergency stop.
        self.maxwaitloop = 10
        self.maxwaitloop_for_read = 1000

        # Actuator speed/distance setup
        self.speed_max = 2000
        self.speed_min = 0
        # scale factor [pulses/mm] mutiplied to distance [mm]
        self.distance_factor = 1000. / 5.5

        # Open communication to the controller
        self.g = None
        self._connect()

        # Initialize Digital IO classes
        # for limit-switch & stopper
        self.ls = DigitalIO(
            'limit-switch', ls_list, self.g, get_onoff_reverse=False)
        self.st = DigitalIO(
            'stopper', st_list, self.g,
            get_onoff_reverse=False, set_onoff_reverse=False)

    def __del__(self):
        self._cleanG()
        print('Actuator:__del__(): '
              'Successfully close the actuator controller.')

    ######################
    # Internal functions #
    ######################

    # Send command & get return function
    # If an error occurs, it raises an error
    def _command(self, cmd, doSleep=True):
        if self.verbose > 0:
            print('Actuator:_command(): command = "{}"\\n'.format(cmd))
        try:
            ret = self.g.GCommand(cmd)
        except Exception as e:
            msg = 'Actuator:_command(): ERROR!: Failed to send command({}).\n'\
                  'Actuator:_command(): ERROR!: Exception = "{}"'\
                  .format(cmd, e)
            print(msg)
            raise
        if self.verbose > 0:
            print('Actuator:_command(): response = "{}"\\n'.format(ret))
        if doSleep:
            time.sleep(self.sleep)
        return ret

    def _cleanG(self):
        if self.g is not None:
            self.g.GClose()
            del self.g
            self.g = None
        if self.verbose > 0:
            print('Actuator:_cleanG(): '
                  'Successfully cleaned the Galil connection')
        return True

    def _connect(self):
        self._cleanG()
        # Open communication to the controller
        print('Actuator:_connect(): '
              'Initialize the Galil actuator controller')
        self.g = gclib.py()
        if self.g is None:
            msg = 'Actuator:_connect() : ERROR!: Failed to '\
                  'initialize the connection to the actuator controller.'
            raise RuntimeError(msg)
        self.g.GOpen('{}'.format(self.ip_address))
        # Connection check
        print('Actuator:_connect(): {}'.format(self.g.GInfo()))
        status = self._check_motortype()
        if not status:
            print('Actuator:_connect(): WARNING! '
                  'Motor type is not correct!')
            print('Actuator:_connect(): '
                  '--> Power off & change the motor types!')
            # Set controller parameters
            # Motor OFF (need for MT command)
            self._set_motor_onoff(onoff=False)
            # Motor type: stepper with active low(2)/high(2.5) step pulses
            self._command('MT 2,2')
        # Motor ON (A,B,N[virtual gear])
        self._set_motor_onoff(onoff=True)
        self._set_actuator_parameters()

        status = self.check_connect()
        if not status:
            msg = 'Actuator:_connect(): ERROR!: '\
                  'check_connect() is failed.'
            raise RuntimeError(msg)
        time.sleep(1)
        print('Actuator:_connect(): Successfully make a connection.')
        return True

    # Set motor ON/OFF
    # Args: onoff = True or False
    def _set_motor_onoff(self, onoff):
        if onoff:  # ON
            self._command('SH AB')
        else:  # OFF
            self._command('MO')
        return True

    # Check the motor type ([2,2] is correct.)
    def _check_motortype(self):
        try:
            ret = self._command('MT ?,?')
            mts = [int(float(motor_type)) for motor_type in ret.split(',')]
        except Exception as e:
            msg = \
                'Actuator:_check_motortype(): ERROR!: Failed to check '\
                'the motor type! | '\
                'Exception = "{}"'.format(e)
            raise RuntimeError(msg)
        if len(mts) != 2:
            print('Actuator:_check_motortype(): '
                  'WARNING!: Returned motor type = {}. '
                  'Array size is not correct.'
                  .format(mts))
            return False
        else:
            if not (mts[0] == 2 and mts[1] == 2):
                print('Actuator:_check_motortype(): '
                      'WARNING!: Returned motor type = {}. '
                      'Motor type is not correct (should be [2,2]).'
                      .format(mts))
                return False
        if self.verbose > 0:
            print('Actuator:_check_motortype(): '
                  'Motor type is correct!')
        return True

    def _set_actuator_parameters(self):
        # Stop motion
        self._command('ST')
        # Set master axis of A & B is N
        self._command('GAA=N')
        self._command('GAB=N')
        # Set gear to N
        self._command('GRA=1')
        self._command('GRB=-1')
        # Smoothing pulse: sample value=16
        self._command('KSA=16')
        self._command('KSB=16')
        # Set current: 3A
        self._command('AGA=3')
        self._command('AGB=3')
        # Set microstepping: 1/8
        self._command('YAA=8')
        self._command('YAB=8')
        # Set motor resolutio: 200 steps/revolution = 1.8deg/step
        self._command('YBA=200')
        self._command('YBB=200')
        self._command('YBN=200')
        # Set speed: speed_max
        self._command('SPA={}'.format(self.speed_max))
        self._command('SPB={}'.format(self.speed_max))
        self._command('SPN={}'.format(self.speed_max))
        # Set positioin
        self._command('PRA=0')
        self._command('PRB=0')
        self._command('PRN=0')
        if self.verbose > 0:
            print('Actuator:_set_actuator_parameters(): '
                  'Successfully set the actuator controller parameters!')
        return True

    ##################
    # Main functions #
    ##################

    # Return: success (True) or failure (False)
    def move(self, distance, speedrate=0.1):
        self._set_actuator_parameters()
        print('Actuator:move(): distance = {}, speedrate = {}'
              .format(distance, speedrate))
        if self.STOP:
            msg = 'Actuator:move(): WARNING!: Did NOT move due to STOP flag.'
            print(msg)
            return False
        if speedrate < 0. or speedrate > 5.:
            print('Actuator:move(): WARNING!: '
                  'Speedrate should be between 0 and 5.')
            print('Actuator:move(): WARNING!: '
                  'Speedrate is set to 1.0.')
            speedrate = 1.0
        speed = \
            int(speedrate * (self.speed_max - self.speed_min) + self.speed_min)
        # distance_count is an absolute value
        distance_count = int(abs(distance) * self.distance_factor)
        # Change the gearing
        if distance >= 0.:
            # Forwarding
            self._command('GRA=1')
            self._command('GRB=-1')
            dlabel = 'forwarding'
        else:
            # Backwarding
            self._command('GRA=-1')
            self._command('GRB=1')
            dlabel = 'backwarding'
        if self.verbose > 0:
            print('Actuator:move(): distance_count = {} ({})'
                  .format(distance_count, dlabel))
        # Set the speed and distance
        self._command('SPA={}'.format(0))
        self._command('SPB={}'.format(0))
        self._command('SPN={}'.format(speed))
        self._command('PRA={}'.format(0))
        self._command('PRB={}'.format(0))
        self._command('PRN={}'.format(distance_count))
        # Start motion
        print('Actuator:move(): Start the moving...')
        self._command('BGN')
        if self.verbose > 0:
            print('Actuator:move(): Succsessfully sent the moving commands!')
        return True

    # Return 1 (running) or 0 (stopping)
    def is_run(self):
        ret = self._command('MG _BGN', doSleep=True)
        isrun = (int)((float)(ret))
        if self.verbose > 0:
            print('Actuator:is_run() : running status = "{}"'.format(isrun))
        return isrun

    # Wait for the end of moving
    # Args: max_loop_time = maximum waiting time [sec]
    # Return: success (True) or failure (False)
    def wait_idle(self, max_loop_time=180):
        # Number of loop for max_loop_time [sec]
        max_loop = int(max_loop_time / self.sleep)
        for i in range(max_loop):
            isrun = self.is_run()
            if not isrun:
                print('Actuator:wait_idle(): The running is finished!')
                return True
        print('Actuator:wait_idle(): ERROR!: '
              'Exceed max. number of loop ({} times)'.format(i))
        return False

    # Check the connection
    def check_connect(self):
        status = self._check_motortype()
        if not status:
            print('Actuator:check_connect(): ERROR!: '
                  'The connection to the actuator controller is BAD!')
            return False
        else:
            if self.verbose > 0:
                print('Actuator:check_connect(): '
                      'The connection to the actuator controller is OK!')
            return True

    def reconnect(self):
        print('Actuator:reconnect() : *** Trying to reconnect... ***')
        for i in range(self.maxwaitloop):
            # reconnect
            print('Actuator:reconnect(): {}th try to reconnection'.format(i))
            try:
                self._connect()
            except Exception as e:
                msg = 'Actuator:reconnect(): WARNING!: '\
                      'Failed to reconnect to the actuator controller! (i={})'\
                      ' | Exception = "{}"'.format(i, e)
                print(msg)
                time.sleep(1)
                continue
            # Set g on DigitalIOs
            self.ls.g = self.g
            self.st.g = self.g
            print('Actuator:reconnect(): '
                  'Successfully reconnect to the actuator controller!')
            return True
        print('Actuator:reconnect(): ERROR!: Exceed the max. number of '
              'trying to reconnect to the actuator controller.')
        return False

    # Get motor ON/OFF
    # Return: 1 (ON) or 0 (OFF)
    def get_motor_onoff(self):
        try:
            # 0: ON, 1:OFF
            retA = self._command('MG _MOA')
            retB = self._command('MG _MOB')
            onoffA = int(float(retA))
            onoffB = int(float(retB))
            # invert to 0: OFF, 1: ON
            onoffA = int(not onoffA)
            onoffB = int(not onoffB)
        except Exception as e:
            msg =\
                'Actuator:get_motor_onoff(): ERROR!: '\
                'Failed to get motor on/off! | '\
                'Exception = "{}"'.format(e)
            print(msg)
            raise
        if onoffA == 1 and onoffB == 1:
            return 1
        elif onoffA == 0 and onoffB == 0:
            return 0
        else:
            msg =\
                'Actuator:get_motor_onoff(): ERROR!: '\
                'Strange status of motor on/off! '\
                'motor A = {} / motor B = {}'.format(
                    'ON' if onoffA else 'OFF',
                    'ON' if onoffB else 'OFF')
            raise RuntimeError(msg)

    # Set motor ON/OFF
    # Args: onoff = True or False
    def set_motor_onoff(self, onoff):
        try:
            self._set_motor_onoff(onoff)
        except Exception as e:
            msg = \
                'Actuator:set_motor_onoff(): ERROR!: '\
                'Failed to set motor {}! | '\
                'Exception = "{}"'\
                .format('ON' if onoff else 'OFF', e)
            print(msg)
            raise
        onoff_test = self.get_motor_onoff()
        if onoff_test != int(onoff):
            msg = \
                'Actuator:set_motor_onoff(): ERROR!: '\
                'Set motor {} but the current ON/OFF ("{}") is different!'\
                .format('ON' if onoff else 'OFF', onoff_test)
            raise RuntimeError(msg)
        print('Actuator:set_motor_onoff(): '
              'Successfully {} the actuator motors!'
              .format('ON' if onoff else 'OFF'))
        return True

    # Return: success (True) or failure (False)
    def stop(self):
        if self.verbose > 0:
            print('Actuator:stop(): Stop the actuator')
        for i in range(self.maxwaitloop):
            self._command('ST')
            isrun = self.is_run()
            if not isrun:
                if self.verbose > 0:
                    print('Actuator:stop(): Successfully stop the actuator!')
                return True
            print('Actuator:stop(): WARNING!: '
                  'Could not stop the actuator! --> Retry')
        print('Actuator:stop(): ERROR!: '
              'Exceed the max. number of retries ({} times).'.format(i))
        return False

    # Return: success (True) or failure (False)
    def hold(self):
        if self.verbose > 0:
            print('Actuator:hold(): Hold the actuator')
        self.STOP = True
        ret = self.stop()
        return ret

    # Release(unhold) the hold state
    def release(self):
        if self.verbose > 0:
            print('Actuator:release(): Release the actuator from hold state')
        self.STOP = False
        if self.verbose > 0:
            print('Actuator:release(): Successfully release the actuator!')
        return True
