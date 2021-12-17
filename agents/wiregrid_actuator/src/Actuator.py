# Built-in python modules
import time
import sys
import os

import serial

class Actuator:
    """
    The Actuator object is for writing commands and reading stats of the actuator via serial communication.
    """

    def __init__(self, devfile='/dev/ttyUSB0', sleep=0.10, verbose=0):
        self.devfile = devfile
        self.sleep   = sleep
        self.verbose = verbose

        self.STOP    = False # This will become True in emergency stop.
        self.maxwaitloop = 10
        self.maxwaitloop_for_read = 1000

        self.Fmax =2000
        self.Fmin =   0

        # Open serial communication
        self.ser = None
        self.ser = serial.Serial(
            self.devfile,
            baudrate=115200,
        )
        if self.ser is None :
            print('Actuator:__init__() : ERROR! Could not open the serial communication to the actuator.')
        else :
            print('Actuator:__init__() : serial = {}'.format(self.ser))
            pass
        self.ser.write(b'\r\n\r\n')
        self.ser.flushInput()
        time.sleep(2)
        res = self.__readAll() # this is necessary to work correctly.
        print('Actuator:__init__() : output of blackbox in the initialization = {}'.format(res))
        # Set blackbox parameters
        self.__setActuatorParameters()
        pass

    def __del__(self) :
        if not self.ser is None :
            self.ser.close()
            del self.ser
            pass
        return True

    ##################
    # Main functions #
    ##################

    # move
    def move(self, distance, speedrate=0.1) :
        if self.STOP:
            msg =  "Actuator:move() : ERROR! Don't move due to STOP flag."
            print(msg)
            return False, msg
        if speedrate<0. or speedrate>1. :
            print("Actuator:move() : WARNING! Speedrate should be between 0 and 1.")
            print("Actuator:move() : WARNING! Speedrate is sed to 0.1.")
            speedrate = 0.1
            pass
        speed = int(speedrate * (self.Fmax-self.Fmin) + self.Fmin)
        cmd  = '$J=G91 F{:d} Y{:d}'.format(speed,distance)
        ret = self.__sendCommand(cmd)
        if not ret :
            msg = 'Actuator:move : ERROR in __sendCommand(command = {})'.format(cmd)
            return False, msg
        msg =  "Actuator:move() : Send command = {}".format(cmd)
        return True, msg

    # get status: return Jog/Idle/Run..
    def getStatus(self, doSleep=True) :
        res = self.__getresponse('?', doSleep).replace('\r','').replace('\n','/').strip()
        if self.verbose>0 : print('Actuator:getStatus() : response to \"?\" = \"{}\"'.format(res))
        status = (res.split('<')[-1].split('>')[0]).split('|')[0].split(':')[0]
        if self.verbose>0 : print('Actuator:getStatus() : status = "{}"'.format(status))
        if len(status)==0 :
            print('Actuator:getStatus() : ERROR! Could not get status!')
            print('Actuator:getStatus() : --> Stop the actuator!')
            self.hold()
            print('Actuator:getStatus() : --> Reconnect to the actuator')
            self.__reconnect()
            res    = self.__getresponse('?', doSleep).replace('\r','').replace('\n','/').strip()
            status = (res.split('<')[-1].split('>')[0]).split('|')[0].split(':')[0]
            if len(status)==0 :
                msg = 'Actuator:getStatus() : ERROR! Could not get status again!'
                print(msg)
                return False, msg
            return True, status
        return True, status

    # status==Idle
    def isIdle(self, doSleep=True):
        ret, status = self.getStatus(doSleep)
        if not ret : return None, 'Actuator:isIdle() : ERROR! Could not get status!'
        if  status == 'Idle' : return True , 'Actuator:isIdle() :'
        else                 : return False, 'Actuator:isIdle() :'
    
    # status==Jog or Run
    def isRun(self, doSleep=True):
        ret, status = self.getStatus(doSleep)
        if not ret : return None, 'Actuator:isRun() : ERROR! Could not get status!'
        if status in ['Jog', 'Run'] : return True , 'Actuator:isRun() :'
        else                        : return False, 'Actuator:isRun() :'

    # Wait for end of moving (until Idle status)
    # max_loop_time : maximum waiting time [sec]
    def waitIdle(self, max_loop_time = 180) :
        max_loop = int(max_loop_time/self.sleep) # # of loop for  max_loop_time [sec]
        for i in range(max_loop) :
            if self.isIdle : return True, 'Actuator:waitIdle() :'
            pass
        msg = 'Actuator:waitIdle() : ERROR! Exceed max number of loop ({} times)'.format(i)
        print(msg)
        return False, msg

    # Check the connection
    def check_connect(self):
        try:
            self.ser.inWaiting()
        except Exception as e:
            msg = 'Actuator:check_connect() : ERROR! Could not connect to the actuator serial! | ERROR: "{}"'.format(e)
            return False, msg
        return True, 'Actuator:check_connect() : Successfully connect to the actuator serial!'


    # Hold
    def hold(self) :
        if self.verbose>0 : print('Actuator:hold() : Hold the actuator')
        self.STOP = True
        for i in range(self.maxwaitloop) :
            self.__sendCommand('!')
            ret, status = self.getStatus(doSleep=True)
            if not ret          : return False, 'Actuator:hold() : Failed to get status!'
            if status == 'Hold' : return True , 'Actuator:hold() : Successfully hold the actuator!'
            print('Actuator:hold() : WARNING! Could not hold the actuator! --> Retry')
            pass
        msg = 'Actuator:hold() : ERROR! Exceed the max number of retry ({} times).'.format(i)
        if self.verbose > 0:
            print(msg)
        return False, msg

    # Release(unhold) the hold state
    def release(self) :
        if self.verbose>0 : print('Actuator:release() : Release the actuator from hold state')
        self.STOP = False
        self.__sendCommand('~')
        return True, 'Successfully finish Actuator:release() :'


    ######################
    # Internal functions #
    ######################

    # Read all strings until the buffer is empty.
    def __readAll(self) :
        lines = ''
        for i in range(self.maxwaitloop_for_read) :
            if self.ser.in_waiting==0 : break  # if buffer is empty, reading is finished.
            else :
                try:
                    line = self.ser.readline().decode()
                except Exception as e:
                    print('Actuator:__readAll() : Failed to readline from actuator! | ERROR = "%s"' % e)
                    continue
                lines += line
                pass
            pass
        if i==self.maxwaitloop-1 : 
            print('Actuator:__readAll() : WARNING! Exceed the max number of loop. ({} times)'.format(i))
            print('Actuator:__readAll() : (size={}) "{}"'.format(len(lines),lines.replace('\n','\\n')))
        else :
            if self.verbose>1 : print('Actuator:__readAll() : (size={}) "{}"'.format(len(lines),lines.replace('\n','\\n')))
            pass
        return lines
    
    # Simple write function
    def __sendCommand(self, command, doSleep=True) :
        if self.verbose>1 :
            print('Actuator:__sendCommand() : command = {}\\n'.format(command))
            #print('Actuator:__sendCommand() : command after encoding = {}'.format((command+'\n').encode()))
            pass
        # wait until out buffer becomes empty
        success_waiting = False
        for i in range(self.maxwaitloop) :
            try : 
                if self.ser is None : break
                out_waiting = self.ser.out_waiting
                if out_waiting == 0 :
                    success_waiting = True
                    break
            except OSError as e:
                msg = 'Actuator:__sendCommand() : ERROR! OSError ({}) in serial.out_waiting'.format(e)
                print(msg)
                time.sleep(self.sleep)
                continue
            pass
        if not success_waiting :
            print('Actuator:__sendCommand() : ERROR! The out_waiting is not 0. (# of loop is over maxloop.) [command:{}] --> Reconnect'.format(command))
            ret, msg = self.__reconnect()
            if not ret :
                print('Actuator:__sendCommand() : ERROR! Failed to reconnect! --> Skip [command:{}]'.format(command))
                return False
            time.sleep(1)
            pass
            
        self.ser.write((command+'\n').encode())
        if doSleep: time.sleep(self.sleep)
        return True
    
    # Send command & get response
    def __getresponse(self, command, doSleep=True) :
        if self.verbose>1 : print('Actuator:__getresponse() : command = {}'.format(command))
        ret = self.__sendCommand(command, doSleep=doSleep)
        if not ret :
            print('Actuator:__getresponse() : ERROR in __sendCommand(command = {})'.format(command))
            return ''
        res = ''
        res = self.__readAll()
        if self.verbose>1 : print('Actuator:__getresponse()  : response = {}'.format(res.replace('\n','\\n')))
        return res

    def __connect(self):
        # Open serial communication
        self.ser = None
        self.ser = serial.Serial(
            self.devfile,
            baudrate=115200,
        )
        if self.ser is None :
            msg = 'Actuator:__connect() : ERROR! Could not open the serial communication to the actuator.'
            print(msg)
            return False, msg
        else :
            print('Actuator:__connect() : serial = {}'.format(self.ser))
            pass
        self.ser.write(b'\r\n\r\n')
        self.ser.flushInput()
        #time.sleep(2)
        res = self.__readAll() # this is necessary to work correctly.
        if self.verbose>0 : print('Actuator:__connect() : output of blackbox in the initialization = {}'.format(res))
        # Set blackbox parameters
        self.__setActuatorParameters()
        msg = 'Actuator:__connect() : Finished make a connection.'
        return True, msg
 

    def __reconnect(self):
        print('Actuator:__reconnect() : *** Trying to reconnect... ***')

        for i in range(self.maxwaitloop) :
            time.sleep(1)
            # reconnect
            print('Actuator:__reconnect() : * {}th try to reconnection'.format(i))
            try :
                if self.ser : 
                   self.ser.close()
                   del self.ser
                ret, msg = self.__connect()
                if not ret:
                    msg = 'Actuator:__reconnect() : WARNING! Failed to reconnect to the actuator!'
                    print(msg)
                    if self.ser : del self.ser
                    self.ser = None
                    continue
            except Exception as e:
                msg = 'Actuator:__reconnect() : WARNING! Failed to initialize Actuator! | ERROR: %s' % e
                print(msg)
                self.ser = None
                continue
            # reinitialize cmd
            ret, msg = self.check_connect()
            if ret :
                msg = 'Actuator:__reconnect() : Successfully reconnected to the actuator!'
                print(msg)
                return True, msg
            else :
                print(msg)
                msg = 'Actuator:__reconnect() : WARNING! Failed to reconnect to the actuator!'
                print(msg)
                if self.ser : del self.ser
                self.ser = None
                continue
            pass
        msg = 'Actuator:__reconnect() : ERROR! Exceed the max number of trying to reconnect to the actuator.'
        print(msg)
        return False, msg


    def __setActuatorParameters(self) :
        #self.__sendCommand('$100=26.667') # step/mm X-axis (not used)
        #self.__sendCommand('$101=26.667') # step/mm Y-axis
        #self.__sendCommand('$102=26.667') # step/mm Z-axis (not used)
        self.__sendCommand('$100=22.220') # step/mm X-axis (not used)
        self.__sendCommand('$101=22.220') # step/mm Y-axis
        self.__sendCommand('$102=22.220') # step/mm Z-axis (not used)
        self.__sendCommand('$110={}'.format(self.Fmax)) # speed [mm/min] X-axis (not used)
        self.__sendCommand('$111={}'.format(self.Fmax)) # speed [mm/min] Y-axis
        self.__sendCommand('$112={}'.format(self.Fmax)) # speed [mm/min] Z-axis (not used)
        self.__sendCommand('$120=10') # accel. [mm/sec^2] X-axis (not used)
        self.__sendCommand('$121=10') # accel. [mm/sec^2] Y-axis
        self.__sendCommand('$122=10') # accel. [mm/sec^2] Z-axis (not used)
        self.__sendCommand('$130=900') # max travel [mm] X-axis (not used)
        self.__sendCommand('$131=900') # max travel [mm] Y-axis
        self.__sendCommand('$132=900') # max travel [mm] Z-axis (not used)
        msg = 'Actuator:__setActuatorParameters : Finished to set actuator controller parameters!'
        print(msg)
        return True, msg
  
 
