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
        self.maxwaitloop = 100000

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
        pass

    def __del__(self) :
        if not self.ser is None :
            self.ser.close()
            del self.ser
            pass
        return 0

    ##################
    # Main functions #
    ##################

    # move
    def move(self, distance, speedrate=0.1) :
        if self.STOP:
            msg =  "Actuator:move() : ERROR! Don't move due to STOP flag."
            print(msg)
            return -1, msg
        if speedrate<0. or speedrate>1. :
            print("Actuator:move() : WARNING! Speedrate should be between 0 and 1.")
            print("Actuator:move() : WARNING! Speedrate is sed to 0.1.")
            speedrate = 0.1
            pass
        Fmax =1000
        Fmin =   0
        speed = int(speedrate * (Fmax-Fmin) + Fmin)
        cmd  = '$J=G91 F{:d} Y{:d}'.format(speed,distance)
        ret = self.__sendCommand(cmd)
        if ret<0 :
            msg = 'Actuator:move : Error in __sendCommand(command = {})'.format(cmd)
            return -1, msg
        msg =  "Actuator:move() : Send command = {}".format(cmd)
        return 0, msg

    # get status: return Jog/Idle/Run..
    def getStatus(self, doSleep=True) :
        res = self.__getresponse('?', doSleep).replace('\r','').replace('\n','/').strip()
        if self.verbose>0 : print('Actuator:getStatus() : response to \"?\" = \"{}\"'.format(res))
        status = (res.split('<')[-1].split('>')[0]).split('|')[0].split(':')[0]
        if self.verbose>0 : print('Actuator:getStatus() : status = \"{}\"'.format(status))
        if len(status)==0 :
            print('Actuator:getStatus() : Error! Could not get status!')
            return -1
        return status

    # status==Idle
    def isIdle(self, doSleep=True):
        if self.getStatus(doSleep) == 'Idle' : return True
        else                                 : return False
    
    # status==Jog or Run
    def isRun(self, doSleep=True):
        status = self.getStatus(doSleep)
        if status in ['Jog', 'Run'] : return True
        else                        : return False

    # Wait for end of moving (until Idle status)
    # max_loop_time : maximum waiting time [sec]
    def waitIdle(self, max_loop_time = 180) :
        max_loop = int(max_loop_time/self.sleep) # # of loop for  max_loop_time [sec]
        for i in range(max_loop) :
            if self.isIdle : return 0
            pass
        print('Actuator:waitIdle() : Error! Exceed max number of loop = {}'.format(i))
        return -1

    # Check the connection
    def check_connect(self):
        try:
            self.ser.inWaiting()
        except Exception as e:
            msg = 'Could not connect to the actuator serial! | Error: "{}"'.format(e)
            return False, msg
        return True, 'Successfully connect to the actuator serial!'


    # Hold
    def hold(self) :
        if self.verbose>0 : print('Actuator:hold() : Hold the actuator')
        while True :
            self.__sendCommand('!')
            if self.getStatus(doSleep=True) == 'Hold' : break
            pass
        return 0

    # Release(unhold) the hold state
    def release(self) :
        if self.verbose>0 : print('Actuator:release() : Release the actuator from hold state')
        self.__sendCommand('~')
        return 0


    ######################
    # Internal functions #
    ######################

    # Read all strings until the buffer is empty.
    def __readAll(self) :
        lines = ''
        while True :
            if self.ser.in_waiting==0 : break  # if buffer is empty, reading is finished.
            else :
                try:
                    line = self.ser.readline().decode()
                except Exception as e:
                    print('Failed to readline from actuator! | Error = "%s"' % e)
                    continue
                lines += line
                pass
            pass
        if self.verbose>0 : print('Actuator:__readAll() : (size={}) "{}"'.format(len(lines),lines))
        return lines
    
    # Simple write function
    def __sendCommand(self, command, doSleep=True) :
        if self.verbose>0 :
            #print('Actuator:__sendCommand() : serial = {}'.format(self.ser))
            print('Actuator:__sendCommand() : command = {}\\n'.format(command))
            print('Actuator:__sendCommand() : command after encoding = {}'.format((command+'\n').encode()))
            pass
        # wait until out buffer becomes empty
        out_waiting = 9999
        for i in range(self.maxwaitloop) :
            out_waiting = self.ser.out_waiting
            if out_waiting == 0 :
                break
            pass
        if out_waiting>0 :
            print('Actuator:__sendCommand() : Error! The out_waiting is not 0. (# of loop is over maxloop.) --> Skip'.format(command))
            return -1
            pass
            
        self.ser.write((command+'\n').encode())
        if doSleep: time.sleep(self.sleep)
        return 0
    
     # Send command & get response
    def __getresponse(self, command, doSleep=True) :
        if self.verbose>0 : print('Actuator:__getresponse : command = {}'.format(command))
        res = ''
        ret = self.__sendCommand(command, doSleep=doSleep)
        if ret<0 :
            print('Actuator:__getresponse : Error in __sendCommand(command = {})'.format(command))
            return ''
        res = self.__readAll()
        if self.verbose > 0 : print('Actuator:__getresponse  : response = {}'.format(res))
        return res

   

  
     
