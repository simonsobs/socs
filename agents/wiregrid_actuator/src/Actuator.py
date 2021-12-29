# Built-in python modules
import time
# Specific module for actuator controller
import gclib
import DigitalIO


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
        self.distance_factor = 1000./5.5

        # Open communication to the controller
        self.g = None
        self._connect()

        # Initialize Digital IO classes
        # for limit-switch & stopper
        self.ls = DigitalIO.DigitalIO(
            'limit-switch', ls_list, self.g, get_onoff_reverse=False)
        self.st = DigitalIO.DigitalIO(
            'stopper', st_list, self.g,
            get_onoff_reverse=False, set_onoff_reverse=False)

    def __del__(self):
        self._cleanG()
        return True,\
            'Actuator:__del__(): '\
            'Successfully close the actuator controller.'

    ######################
    # Internal functions #
    ######################
    # Return: status(True or False), message
    # If an error occurs, return False except _command().

    # Send command & get return function
    # If an error occurs, raise the error unlike the other functions
    def _command(self, cmd, doSleep=True):
        if self.verbose > 1:
            print('Actuator:_command(): command = "{}"\\n'.format(cmd))
        try:
            ret = self.g.GCommand(cmd)
        except Exception as e:
            msg = 'Actuator:_command(): ERROR! Failed to send command({}).\n'\
                  'Actuator:_command(): ERROR! Error: {}'.format(cmd, e)
            print(msg)
            raise
        if self.verbose > 1:
            print('Actuator:_command(): response = "{}"\\n'.format(ret))
        if doSleep:
            time.sleep(self.sleep)
        return True, ret

    def _cleanG(self):
        if self.g is not None:
            self.g.GClose()
            del self.g
            self.g = None
        return True, 'Successfully clean Galil connection'

    def _connect(self):
        self._cleanG()
        # Open communication to the controller
        print('Actuator:_connect(): '
              'Initialize the Galil actuator controller')
        self.g = gclib.py()
        if self.g is None:
            msg = 'Actuator:_connect() : ERROR! Failed to '\
                  'initialize the connection to the actuator controller.'
            print(msg)
            return False, msg
        self.g.GOpen('{}'.format(self.ip_address))
        # Connection check
        print('Actuator:_connect(): {}'.format(self.g.GInfo()))
        ret, msg = self.check_connect()
        if not ret:
            msg = 'Actuator:_connect(): ERROR! Failed to check '\
                  'the connection to the actuator controller.: {}'.format(msg)
            print(msg)
            return False, msg
        # Set controller parameters
        # Motor OFF (need for MT command)
        self._command('MO')
        # Motor type: stepper with active low(2)/high(2.5) step pulses
        self._command('MT 2,2')
        # Motor ON (A,B,N[virtual gear])
        self._command('SH ABN')
        self._set_actuator_parameters()

        time.sleep(1)
        msg = 'Actuator:_connect(): Successfully make a connection.'
        return True, msg

    def _reconnect(self):
        print('Actuator:_reconnect() : *** Trying to reconnect... ***')
        for i in range(self.maxwaitloop):
            # reconnect
            print('Actuator:_reconnect(): {}th try to reconnection'.format(i))
            ret, msg = self._connect()
            if not ret:
                msg = 'Actuator:_reconnect(): '\
                      'WARNING! Failed to reconnect to the actuator!'
                print(msg)
                self._cleanG()
                time.sleep(1)
                continue
            else:
                time.sleep(1)
                msg = 'Actuator:_reconnect(): '\
                      'Successfully reconnect to the actuator controller!'
                return True, msg
        msg = 'Actuator:_reconnect(): ERROR! Exceed the max. number of '\
              'trying to reconnect to the actuator controller.'
        print(msg)
        return False, msg

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
        msg = 'Actuator:_set_actuator_parameters(): \
            Successfully set the actuator controller parameters!'
        return True, msg

    ##################
    # Main functions #
    ##################
    # Return: status(True or False), message
    # If an error occurs, raise an error

    # move
    def move(self, distance, speedrate=0.1):
        self._set_actuator_parameters()
        print('Actuator:move(): distance = {}, speedrate = {}'
              .format(distance, speedrate))
        if self.STOP:
            msg = 'Actuator:move(): ERROR! Did NOT move due to STOP flag.'
            print(msg)
            raise RuntimeError(msg)
        if speedrate < 0. or speedrate > 1.:
            print('Actuator:move(): WARNING! '
                  'Speedrate should be between 0 and 1.')
            print('Actuator:move(): WARNING! '
                  'Speedrate is sed to 0.1.')
            speedrate = 0.1
        speed = \
            int(speedrate * (self.speed_max-self.speed_min) + self.speed_min)
        distance_count = int(distance * self.distance_factor)
        print('Actuator:move(): distance_count = {}'.format(distance_count))
        self._command('SPA={}'.format(0))
        self._command('SPB={}'.format(0))
        self._command('SPN={}'.format(speed))
        self._command('PRA={}'.format(0))
        self._command('PRB={}'.format(0))
        self._command('PRN={}'.format(distance_count))
        # Start motion
        print('Actuator:move(): Start the moving...')
        self._command('BGN')
        msg = 'Actuator:move(): Succsessfully send move commands'
        return True, msg

    # return True, True or False
    def is_run(self):
        status, ret = self._command('MG _BGN', doSleep=True)
        # print('Actuator:is_run() : "{}"'.format(ret))
        isrun = (int)((float)(ret))
        if self.verbose > 0:
            print('Actuator:is_run() : running status = "{}"'.format(isrun))
        return True, isrun

    # Wait for the end of moving
    # max_loop_time : maximum waiting time [sec]
    def wait_idle(self, max_loop_time=180):
        # Number of loop for max_loop_time [sec]
        max_loop = int(max_loop_time/self.sleep)
        for i in range(max_loop):
            ret, isrun = self.is_run()
            if not isrun:
                return True,\
                    'Actuator:wait_idle(): Successfully running is finished!'
        msg = 'Actuator:wait_idle(): ERROR! '\
              'Exceed max. number of loop ({} times)'.format(i)
        print(msg)
        return False, msg

    # Check the connection
    def check_connect(self):
        try:
            status, ret = self._command('MT ?,?')
            mts = [int(float(motor_type)) for motor_type in ret.split(',')]
        except Exception as e:
            msg = \
                'Actuator:check_connect(): ERROR! Failed to check '\
                'the connection to the actuator controller! |'\
                'ERROR: "{}"'.format(e)
            print(msg)
            raise RuntimeError(msg)
        if len(mts) != 2:
            msg = \
                'Actuator:check_connect(): ERROR! Failed to check '\
                'the connection to the actuator controller! | '\
                'ERROR: "Returned motor type = {}. '\
                'Array size is not correct."'\
                .format(mts)
            print(msg)
            raise RuntimeError(msg)
        else:
            if not (mts[0] == 2 and mts[1] == 2):
                msg = \
                    'Actuator:check_connect(): ERROR! Failed to check '\
                    'the connection to the actuator controller! |'\
                    'ERROR: "Returned motor type is not correct: {}"'\
                    .format(mts)
                print(msg)
                raise RuntimeError(msg)
        return True,\
            'Actuator:check_connect(): '\
            'Successfully check the connection to the actuator controller!'

    # Get motor ON/OFF
    def get_motor_onoff(self):
        try:
            status, ret = self._command('MG _MON')
            onoff = int(float(ret))
        except Exception as e:
            msg = \
                'Actuator:get_motor_onoff(): ERROR! '\
                'Failed to get motor on/off! | '\
                'ERROR: {}'.format(e)
            print(msg)
            return False, msg
        return True, onoff

    # Set motor ON/OFF
    def set_motor_onoff(self, onoff):
        try:
            if not onoff:  # OFF
                status, ret = self._command('MON')
            else:  # ON
                status, ret = self._command('SH ABN')
        except Exception as e:
            msg = \
                'Actuator:set_motor_onoff(): ERROR! '\
                'Failed to set motor {}! | '\
                'ERROR: {}'\
                .format('ON' if onoff is True else 'OFF', e)
            print(msg)
            return False, msg
        return True,\
            'Actuator:set_motor_onoff(): '\
            'Successfully {} the actuator motors!'\
            .format('ON' if onoff is True else 'OFF')

    # Hold
    def hold(self):
        if self.verbose > 0:
            print('Actuator:hold(): Hold the actuator')
        self.STOP = True
        for i in range(self.maxwaitloop):
            self._command('ST')
            ret, isrun = self.is_run()
            if not ret:
                msg = 'Actuator:hold(): ERROR! Failed to get status!'
                print(msg)
                return False, msg
            if not isrun:
                msg = 'Actuator:hold(): Successfully hold the actuator!'
                return True, msg
            print('Actuator:hold(): WARNING! '
                  'Could not hold the actuator! --> Retry')
        msg = 'Actuator:hold(): ERROR! '\
              'Exceed the max. number of retries ({} times).'.format(i)
        print(msg)
        return False, msg

    # Release(unhold) the hold state
    def release(self):
        if self.verbose > 0:
            print('Actuator:release(): Release the actuator from hold state')
        self.STOP = False
        return True, 'Actuator:release(): Successfully release the actuator!'
