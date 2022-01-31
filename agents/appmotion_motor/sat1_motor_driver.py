####################################################################################################
#
# FTS Control for UCSD
#
# Kevin Crowley and Lindsay Ng Lowry
# llowry@ucsd.edu
# 20180320
#
# This program was modified from the FTSControl.py code used in KEK during Run38 testing of PB2a
# (written by Fred Matsuda) to work with the FTSs at UCSD.  It sets up the FTSControl objects that
# are used to control the two motors (output polarizer and linear stage) that are used by the FTS.
# This assumes the motor controllers have been configured properly using the ST Configurator Windows
# application.
#
# NEED TO DOCUMENT HOW THE MOTOR CONTROLLERS SHOULD BE CONFIGURED.
#
# Commands for communicating with the motor controllers can be found here:
# https://www.applied-motion.com/sites/default/files/hardware-manuals/Host-Command-Reference_920-0002P.PDF
#
####################################################################################################


####################################################################################################
#
# Motor Control for UCSD Remy/Joe 11/15 Update!!
#
#
# This update modifies the FTS Control code to be 'more general' in regards to docstrings and variable 
# names. By this we aim to transition FTS/Polarizer instances to motor1/motor2/motorN instances instead.
# Also, we plan to update functions to act smarter, specifically... 
# 
# NEED TO DOCUMENT HOW THE MOTOR CONTROLLERS SHOULD BE CONFIGURED.
#
# Commands for communicating with the motor controllers can be found here:
# https://www.applied-motion.com/sites/default/files/hardware-manuals/Host-Command-Reference_920-0002P.PDF
#
####################################################################################################


import sys
from MoxaSerial import Serial_TCPServer
from time import sleep
import numpy as np
# from pylab import load

# Time to wait for the user to power on the controllers and to see the power-on signature from the serial port
DEFAULT_WAIT_START_TIME = 15.0 #seconds

# Motor Names
MOTOR1 = 1
MOTOR2 = 2
ALL = 3

# Conversions for stages
AXIS_THREADS_PER_INCH_STAGE = 10.0 #Conversion for the FTS Linear Stage - Check for factor of two later
AXIS_THREADS_PER_INCH_XYZ = 10.0 #Measured on stepper, Check for factor of two later
#AXIS_THREADS_PER_INCH = 10.0 #Measured on stepper
MR_CODE_TO_STEPS_PER_REV = {
        '3': 2000.0,
        '4': 5000.0,
        '5': 10000.0,
        '6': 12800.0,
        '7': 18000.0,
        '8': 20000.0,
        '9': 21600.0,
        '10': 25000.0,
        '11': 25400.0,
        '12': 25600.0,
        '13': 36000.0,
        '14': 50000.0,
        '15': 50800.0
}




class MotControl(object):
        """Object for controlling up to 2 motors - all functions will work for linear stages, some will work if motors are attached
        to non-linear stages. 
        """
        def __init__(self, motor1_Ip=None, motor1_Port=None, motor1_isLin = True, motor2_Ip=None, motor2_Port=None, motor2_isLin = True, mRes=False):
                """Initialize a MotControl object.

                Parameters:
                UPDATE********************
                motor1_Ip (str) -- the IP address associated with the linear stage motor
                motor1_Port (int) -- the port address associated with the linear stage motor
                motor2_Ip (str) -- the IP address associated with the output polarizer motor
                motor2_Port (int) -- the port address associated with the output polarizer motor
                mRes (bool) -- True if manual resolution, False if default (res=8) ???
                """

                # Set up the connection to the first motor
                # Initialized so that the startup position is set to zero
                if not (motor1_Ip and motor1_Port):
                        print("Invalid Motor 1 information.  No Motor 1 control.")
                        self.motor1 = None
                else:
                        self.motor1 = Serial_TCPServer((motor1_Ip, motor1_Port))
                        if mRes:
                                self.motor1.propDict = {
                                        'name': 'motor1',
                                        'motor': MOTOR1,
                                        'res': 'manual',
                                        'pos': 0, #Position in counts (should always be an integer)
                                        'realPos': 0.0, #Position in inches
                                        'sPRev': 8000.0, #Steps per revolution (thread)
                                        'isLin': motor1_isLin
                                }
                        else:
                                self.motor1.propDict = {
                                        'name': 'motor1',
                                        'motor': MOTOR1,
                                        'res': '8', #Corresponds to mapping above
                                        'pos': 0, #Position in counts (should always be an integer)
                                        'realPos': 0.0, #Position in inches
                                        'sPRev': MR_CODE_TO_STEPS_PER_REV['8'], #Steps per revolution (thread)
                                        'isLin': motor1_isLin
                                }

                # Set up the connection to the second motor
                # Initialized so that the startup position is set to zero
                if not (motor2_Ip and motor2_Port):
                        print("Invalid Motor 2 information.  No Motor 2 control.")
                        self.motor2 = None
                else:
                        self.motor2 = Serial_TCPServer((motor2_Ip, motor2_Port))
                        if mRes:
                                self.motor2.propDict = {
                                        'name': 'motor2',
                                        'motor': MOTOR2,
                                        'res': 'manual',
                                        'pos': 0, #Position in counts
                                        'realPos': 0, #Position in inches
                                        'sPRev': 8000.0, #Steps per revolution (thread)
                                        'isLin': motor2_isLin
                                }
                        else:
                                self.motor2.propDict = {
                                        'name': 'motor2',
                                        'motor': MOTOR2,
                                        'res': '8', #Corresponds to mapping above
                                        'pos': 0, #Position in counts
                                        'realPos': 0.0, #Position in inches
                                        'sPRev': MR_CODE_TO_STEPS_PER_REV['8'], #Steps per revolution (thread)
                                        'isLin': motor2_isLin
                                }

                for motor in [self.motor1, self.motor2]:
                        if motor:
                                # Check to make sure the device is in receive mode and reset if necessary
                                msg = motor.writeread(b'RS\r') #RS = Request Status
                                motor.flushInput()
                                print(msg)
                                if (msg == b'RS=R'):
                                        print("%s in receive mode." % (motor.propDict['name']))
                                elif (msg != b'RS=R'):
                                        print("%s not in receive mode.  Resetting." % (motor.propDict['name']))
                                        print("Message was: ",msg)
                                        self.killAllCommands(motor.propDict['motor'])
                                        if (msg == b'RS=AR'):
                                                amsg = motor.writeread(b'AL\r') #AL = Alarm Code
                                                print('Alarm message is: ',amsg)
                                                print("Alarm was found. Resetting.")
                                                motor.write(b'AR\r') #AR = Alarm Reset
                                                motor.flushInput()
                                        else:
                                                print('Irregular message received.')
                                                sys.exit(1)

                                # Check the microstep resolution
                                if mRes:
                                        motor.write(b'EG8000\r') #EG = Electronic Gearing
                                        motor.write(b'SA\r') #SA = Save Parameters
                                        motor.flushInput()
                                        sleep(0.1)
                                        msg = motor.writeread(b'EG\r')
                                        motor.flushInput()
                                        if(len(msg) <= 4):    # Need at least MR=X + \r, which is 5 characters
                                                print("Couldn't get microstep resolution for %s.  Assuming 8." % (motor.propDict['name']))    # keeps params from initialization?
                                        else:
                                                print(msg)
                                                msInfo = msg.rstrip('\r')[3:]
                                                motor.propDict['sPRev'] = float(msInfo)
                                else:
                                        msg = motor.writeread(b'MR\r') #MR = Microstep Resolution
                                        motor.flushInput()
                                        if(len(msg) <= 3):    # Need at least MR=X + \r, which is 5 characters
                                                print("Couldn't get microstep resolution for %s.  Assuming 8." % (motor.propDict['name']))    # keeps params from initialization?
                                        else:
                                                msInfo = msg.rstrip(b'\r')[3:]
                                                msInfo = msInfo.decode('utf-8')
                                                print(msInfo)
                                                motor.propDict['res'] = msInfo
                                                motor.propDict['sPRev'] = MR_CODE_TO_STEPS_PER_REV[msInfo]

                        # Set up the limit switches (as normally closed) and check the operating current for the stage motor

                        if (motor != None) and (motor.propDict['isLin']):
                                msg = motor.writeread(b'DL\r') #DL = Define Limits
                                if msg != b'DL=2':
                                        print("Limits not defined as normally open. Resetting...")
                                        motor.write(b'DL2\r')
                                        sleep(0.1)
                                        motor.flushInput()
                                msg = motor.writeread(b'CC\r') #CC = Change Current
                                print(msg)
                                current = float(msg[3:])
                                if current < 1.5:
                                        print("Operating current insufficient. Resetting...")
                                        motor.write(b'CC1.5\r')
                        else:
                                if motor != None:
                                        motor.write(b'JE\r') #JE = Jog Enable


        def genMotorList(self, motor):
                """Get a list of the motors in a MotControl object.

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL

                Returns:
                mList (list) -- list of desired motors
                """
                mList = []
                if motor==MOTOR1 or motor==ALL: mList.append(self.motor1)
                if motor==MOTOR2 or motor==ALL: mList.append(self.motor2)
                return mList

        def isMoving(self, motor=ALL, verbose=False):
                """Returns True if either motor is moving, False if both motors are not moving. 
                Also returns True if the motor provides an irregular status message, such as any alarm keys.

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)
                verbose (bool) -- prints output from motor requests if True (default False)
                """
                mList = self.genMotorList(motor)

                for motor in mList:
                        motor.flushInput()

                        # Get the status of the motor and print if verbose = True
                        msg = motor.writeread(b'RS\r') #RS = Request Status
                        name = motor.propDict['name']
                        motor.flushInput()
                        if verbose:
                                print(msg)
                                sys.stdout.flush()
                        # If either motor is moving, immediately return True
                        if (msg == b'RS=FMR'):
                                if verbose:
                                    print(f'Motor {name} is still moving.')
                                return True
                        elif (msg == b'RS=R'):
                                if verbose:
                                    print(f'Motor {name} is not moving.')
                                continue
                        elif (msg == b'RS=AR'):
                                if verbose:
                                        print(msg)
                                # Check what the alarm message is
                                msg = motor.writeread(b'AL\r')
                                if (msg == b'AL=0002'):
                                        print('CCW limit switch hit unexpectedly.')
                                        return True
                                elif (msg == b'AL=0004'):
                                        print('CW limit switch hit unexpectedly.')
                                        return True
                        else:
                                print(f'Irregular error message for motor {name}: {msg}')
                                return True
                
                if verbose:
                    print('Neither motor is moving.')
                return False
        
        def homeWithLimits(self, motor=ALL):
                """Uses the limit switches to zero all motor positions. 
                This function should only be used if the linear stages do not have 
                home switches, and should be done carefully. Does one motor at a time
                in order to be careful.

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)
                """

                mList = self.genMotorList(motor)
                
                for motor in mList:
                        if motor is None:
                                print('Specified motor is invalid -- exiting function')
                                return
                        mot_id = motor.propDict['motor']
                        # Basically, move motors until it hits the limit switch. This will trigger an alarm
                        self.moveAxisByLength(motor=mot_id,pos=-30,posIsInches=True)
                        
                        # Check if either motor is moving, and if yes exit function with an error message
                        move_status = self.isMoving(motor)
                        if move_status:
                                print('Motors are still moving. Try again later.')
                                return

                        
                        moving = True
                        while moving:
                                msg = motor.writeread(b'AL\r')
                                # This is the error message for the limit switch near the motor
                                if (msg == b'AL=0002'):
                                        print('Reached CCW limit switch. Moving 1 inch away from limit switch')
                                        pos = int(1.0*AXIS_THREADS_PER_INCH_STAGE*motor.propDict['sPRev']/2.0)
                                        motor.write(b'DI%i\r' % (pos)) #DI = Distance/Position
                                        motor.write(b'FL\r') #FL = Feed to Length
                                        motor.flushInput()
                                        
                                        # Wait for motor to get off limit switch and reset alarms
                                        sleep(3)
                                        print('Resetting alarms')
                                        self.resetAlarms(motor=mot_id)

                                if not self.isMoving(motor=mot_id):
                                        # zero motor and encoder
                                        print(f'Zeroing {motor}')
                                        self.setZero(motor=mot_id)
                                        self.setEncoderValue(motor=mot_id)
                                        # move on to next stage
                                        moving = False
                        print('Stage zeroed using limit switch')
                
        
        def startJogging(self, motor=ALL):
                """Starts jogging control for specified motors."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - not starting jogging.")
                                continue
                        motor.write(b'JE\r') #JE = Jog Enable
                        motor.write(b'WI4L\r') #WI = Wait for Input - Set into wait mode on empty input pin
                        motor.flushInput()


        def stopJogging(self, motor=ALL):
                """Stop jogging control."""
                self.killAllCommands(motor)


        def seekHomeLinearStage(self, motor=MOTOR1):
                """Move the linear stage to its home position (using the home limit switch)."""
                
                # Check if either motor is moving, and if yes exit function with an error message
                move_status = self.isMoving(motor)
                if move_status:
                        print('Motors are still moving. Try again later.')
                        return
                
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no motion.")
                                continue
                                
                        # Perhaps generalize to 'if not motor' print message... (isLin bool variable probably)
                        elif not motor.propDict['isLin']:
                                print("Motor isn't connected to a linear stage.")
                                continue
                        motor.write(b'VE2.0\r') #VE = Velocity
                        motor.write(b'AC2.0\r') #AC = Acceleration Rate
                        motor.write(b'DE2.0\r') #DE = Deceleration
                        motor.write(b'DI-1\r') #DI = Distance/Position (sets direction)
                        motor.write(b'SHX3L\r') #SH = Seek Home
                        motor.flushInput()
                        print("Linear stage homing...")
                        self.blockWhileMoving(motor.propDict['motor'],verbose=True)
                print("Linear stage home found.")

        def setZero(self, motor=ALL):
                """Tell the motor to set the current position as the zero point."""
                # Check if either motor is moving, and if yes exit function with an error message
                move_status = self.isMoving(motor)
                if move_status:
                        print('Motors are still moving. Try again later.')
                        return

                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid.")
                                continue
                        motor.propDict['pos'] = 0
                        motor.propDict['realPos'] = 0.0
                        motor.write(b'SP0\r') #SP = Set Position
                        motor.flushInput()


        def getPosition(self, motor=ALL):
                """Get the position of the motor in counts, relative to the set zero point (or starting point).

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)

                Returns:
                positions (list) -- the positions in counts of the specified motors
                """
                mList = self.genMotorList(motor)
                positions = []
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no position info.")
                                positions.append(None)
                        else:
                                positions.append(motor.propDict['pos'])
                return positions


        def getPositionInInches(self, motor=ALL):
                """Get the position of the motor in inches, relative to the set zero point (or starting point).

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)

                Returns:
                realPositions (list) -- the positions in inches of the specified motors
                """
                mList = self.genMotorList(motor)
                realPositions = []
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no position info.")
                                realPositions.append(None)
                        else:
                                realPositions.append(motor.propDict['realPos'])
                return realPositions
        
        def getImmediatePosition(self, motor=ALL, inches=True):
                """Get the position of the motor while it is currently in motion. An estimate based on the 
                calculated trajectory of the movement, relative to the zero point.

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)
                inches (bool) -- whether the returned position should be inches or not

                Returns:
                positions (list) -- the positions of each motor, in either inches or counts.

                """
                mList = self.genMotorList(motor)
                positions = []

                counts_to_inches = 100000 # empirically, 100,000 counts per inch
                
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no encoder info.")
                                continue
                        # Check that the motor position output is in the right mode
                        msg = motor.writeread(b'IF\r')
                        if msg == b'IF=H':
                                # Output is coming out in hexadecimal, switching to decimal
                                print('Changing output to decimal')
                                motor.writeread(b'IFD\r')

                        iPos = motor.writeread(b'IP\r')
                        sleep(0.1)
                        motor.flushInput()
                        iPos = int(iPos.rstrip(b'\r')[3:])
                        if inches:
                                iPos = iPos/counts_to_inches
                        positions.append(iPos)
                return positions


                
        
        def moveAxisToPosition(self, motor=MOTOR1, pos=0, posIsInches=False, linStage=True):
                """Move the axis to the given absolute position in counts or inches.

                Parameters:
                motor (int/motor name) - MOTOR1, MOTOR2, or ALL (default MOTOR1)
                pos (float) - the desired position in counts or in inches, positive indicates away from the motor (default 0)
                posIsInches (bool) - True if pos was specified in inches, False if in counts (default False)
                linStage (bool) - True if the specified motor is for the linear stage, False if not (default True)
                """
                
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no motion.")
                                continue
                        # Set the threads per inch based on if the motor controls the FTS linear stage
                        if linStage:
                                AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
                        else:
                                AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

                        # Convert from inches if necessary
                        if(posIsInches): unitPos = int(pos*AXIS_THREADS_PER_INCH*motor.propDict['sPRev']/2.0) #2.0 is because threads go twice the distance for one revolution
                        else: unitPos = int(pos)

                        # Set the new pos and realPos parameters of the motor object
                        motor.propDict['pos'] = unitPos
                        motor.propDict['realPos'] = 2.0*unitPos/(AXIS_THREADS_PER_INCH*motor.propDict['sPRev']) #See 2.0 note above

                        # Move the motor
                        motor.write(b'DI%i\r' % (unitPos)) #DI = Distance/Position
                        motor.write(b'FP\r') #FL = Feed to Position
                        motor.flushInput()


        def moveAxisByLength(self, motor=MOTOR1, pos=0, posIsInches=False, linStage=True):
                """Move the axis relative to the current position by the specified number of counts or inches.

                Parameters:
                motor (int/motor name) - MOTOR1, MOTOR2, or ALL (default MOTOR1)
                pos (float) - the desired number of counts or inches to move from current position, positive indicates away from the motor (default 0)
                posIsInches (bool) - True if pos was specified in inches, False if in counts (default False)
                linStage (bool) - True if the specified motor is for the linear stage, False if not (default True)
                """
                
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no motion.")
                                continue
                        # Set the threads per inch based on if the motor controls the FTS linear stage
                        if linStage:
                                AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
                        else:
                                AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

                        # Convert from inches if necessary
                        if(posIsInches): unitPos = int(pos*AXIS_THREADS_PER_INCH*motor.propDict['sPRev']/2.0) #See 2.0 note above
                        else: unitPos = int(pos)

                        # Set the new pos and realPos parameters of the motor object
                        motor.propDict['pos'] += unitPos
                        motor.propDict['realPos'] += 2.0*unitPos/(AXIS_THREADS_PER_INCH*motor.propDict['sPRev']) #See 2.0 note above

                        # Move the motor
                        motor.write(b'DI%i\r' % (unitPos)) #DI = Distance/Position
                        motor.write(b'FL\r') #FL = Feed to Length
                        motor.flushInput()
                        print("Final position: ",pos)


        def setVelocity(self, motor=ALL, velocity=1.0):
                """Set velocity in revolutions/second.  Range is .025 - 50.  Accepts floating point values."""
                # Check if either motor is moving, and if yes exit function with an error message
                move_status = self.isMoving(motor)
                if move_status:
                        print('Motors are still moving. Try again later.')
                        return
                
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no velocity set.")
                                continue
                        motor.write(b'VE%1.3f\r' % (velocity)) #VE = Velocity
                        motor.flushInput()


        def setAcceleration(self, motor=ALL, accel=5):
                """Set acceleration in revolutions/second/second.  Range is 1-3000.  Accepts only integer values."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no acceleration set.")
                                continue
                        motor.write(b'AC%i\r' % (accel)) #AC = Acceleration Rate
                        motor.write(b'DE%i\r' % (accel)) #DE = Deceleration
                        motor.flushInput()


        def killAllCommands(self, motor=ALL):
                """Stop all active commands on the device."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no motion.")
                                continue
                        motor.write(b'SK\r') #SK = Stop & Kill - Stop/kill all commands, turn off waiting for input
                        motor.flushInput()


        def blockWhileMoving(self, motor=ALL, updatePeriod=.1, verbose=False):
                """Block until the specified axes have stop moving.  Checks each axis every updatePeriod seconds.

                Parameters:
                motor (int/motor name) -- MOTOR1, MOTOR2, or ALL (default ALL)
                updatePeriod (float) -- time after which to check each motor in seconds (default .1)
                verbose (bool) -- prints output from motor requests if True (default False)
                """
                mList = self.genMotorList(motor)
                count = 0
                while(mList):
                        count += 1
                        for motor in mList:
                                motor.flushInput()

                                # Get the status of the motor and print if verbose = True
                                msg = motor.writeread(b'RS\r') #RS = Request Status
                                motor.flushInput()
                                if verbose:
                                        print(msg)
                                        sys.stdout.flush()
                                # Remove the motor from mList (so that the while loop continues) only if the status is not "Ready"
                                if(msg == b'RS=R'):
                                        mList.remove(motor) #Should only be in the list once
                        # Break if too many while loop iterations - indicates potential problem
                        if count > 2000:
                                print('Motion taking too long, there may be a different failure or alarm...')
                                break

                        # Wait the specified amount of time before rechecking the status
                        sleep(updatePeriod)
                print('')

        def runPositions(self, posData, motor=ALL, posIsInches = False):
                """Runs a tab-delimited list of entries as positions from a text file.  For AXIS_ALL, the first column
                must be the x-data, and the second column the y-data.  Each position will be attained.
                xPosition and yPosition will be specified as in the file."""
                # Check if either motor is moving, and if yes exit function with an error message
                move_status = self.isMoving(motor)
                if move_status:
                        print('Motors are still moving. Try again later.')
                        return
                
                if(len(posData) > 0):
                        #This is for the 2-axis case.  In the 1-axis case, posData[0] will just be a floating point value
                        if motor == ALL and len(posData) < 2:
                                raise Exception("You specified that both axes would be moving, but didn't provide data for both.")
                for pos in posData:
                        if motor == ALL:
                                self.moveAxisToPosition(MOTOR1, posData[0], posIsInches=posIsInches)
                                self.moveAxisToPosition(MOTOR2, posData[1], posIsInches=posIsInches)
                        elif motor == MOTOR1:
                                self.moveAxisToPosition(MOTOR1, pos, posIsInches=posIsInches) #Should be a scalar for pos
                        elif motor == MOTOR2:
                                self.moveAxisToPosition(MOTOR2, pos, posIsInches=posIsInches) #Should be a scalar for pos

                print(f'Moving position to {pos}')


        def setMotorEnable(self, motor=ALL, enable=True):
                """Set motor enable to true or false for given axis.  Should disable motor when stopped for lower noise data acquisition."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - cannot enable.")
                                continue
                        if enable==True: motor.write(b'ME\r') #ME = Motor Enable
                        else: motor.write(b'MD\r') #MD = Motor Disable
                        motor.flushInput()


        def retrieveEncoderInfo(self, motor=ALL):
                """Retrieve all motor step counts to verify movement."""
                move_status = self.isMoving(motor)

                mList = self.genMotorList(motor)

                ePositions = []

                # If the motors are moving, return NaNs to keep from querying the
                # motor controllers during motion.
                if move_status:
                        for motor in mList:
                                ePositions.append(np.nan)
                        return ePositions

                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no encoder info.")
                                continue
                        ePos = motor.writeread(b'EP\r') #EP = Encoder Position
                        sleep(0.1)
                        motor.flushInput()
                        ePos = int(ePos.rstrip(b'\r')[3:])
                        ePositions.append(ePos)
                return ePositions


        def setEncoderValue(self, motor=ALL, value=0):
                """Set the encoder values in order to keep track of absolute position"""
                # Check if either motor is moving, and if yes exit function with an error message
                move_status = self.isMoving(motor)
                if move_status:
                        print('Motors are still moving. Try again later.')
                        return
                
                mList = self.genMotorList(motor)
                ePositions = []
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - encoder value not set.")
                                continue
                        # Set the motor position
                        ePosSet = motor.write(b'EP%i\r'%(value)) #EP = Encoder Position
                        sleep(0.1)
                        motor.flushInput()
                        # Read and return the new motor position
                        ePos = motor.writeread(b'EP\r') #EP = Encoder Position
                        sleep(0.1)
                        motor.flushInput()
                        ePos = int(ePos.rstrip(b'\r')[3:])
                        print(ePos)
                        ePositions.append(ePos)
                return ePositions


        def startRotation(self, motor=MOTOR2, velocity=12.0, accel=1.0):
                """Starts jogging specifically for the rotation of the output polarizer in the FTS.

                Parameters:
                motor (int/motor name) -- desired motor (default MOTOR2)
                velocity (float) -- the rotation velocity in revolutions/second (default 12.0)
                accel (float) -- the acceleration in revolutions/second/second (default 1.0)
                """
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - not starting jogging.")
                                continue

                        # Set the jog parameters
                        motor.write(b'JS%1.3f\r' % (velocity)) #JS = Jog Speed
                        motor.write(b'JA%i\r' % (accel)) #JA = Jog Acceleration
                        motor.write(b'JL%i\r' % (accel)) #JL = Jog Decel

                        # Start rotation
                        motor.write(b'CJ\r') #CJ = Commence Jogging
                        motor.flushInput()


        def stopRotation(self, motor=MOTOR2):
                """Stops jogging specifically for the rotation of MOTOR2."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid.")
                                continue
                        motor.write(b'SJ\r') #SJ = Stop Jogging
                        motor.flushInput()

        def resetAlarms(self, motor=ALL):
                """Resets alarm codes present. Only advised if you have checked what the alarm is first!

                Parameters:
                motor (int/motor name) -- desired motor (default ALL)
                """

                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid.")
                                continue
                        motor.write(b'AR\r')
                        motor.flushInput()


        def closeConnection(self, motor=ALL):
                """Close the connection to the serial controller for the specified motor."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no connection to close.")
                                continue
                        motor.sock.close()
                print("Connection to serial controller disconnected.")

                
#  ##################################################################################################               
#       Try to reset socket connection!! - need to look up how to do this. too cold outside rn :(
#  ##################################################################################################
        def resetConnection(self, motor=ALL):
                """Close the connection to the serial controller for the specified motor."""
                mList = self.genMotorList(motor)
                for motor in mList:
                        if not motor:
                                print("Specified motor is invalid - no connection to close.")
                                continue
                        motor.sock.close()
                print("Connection to serial controller disconnected.")
        
        """
        ##############################################################################################
        # don't know if we want this!! - no init_stages() first off. unsure how to match LATRt :(
        ##############################################################################################
        @classmethod
        def SAT1MotorDriver(cls, IP1, PORT1, ISLIN1, IP2=None, PORT2=None, ISLIN2=False, MRES=False):
            HOST = '192.168.10.15'
            PORT = 3010

            motors = cls(IP1, PORT1, ISLIN1, IP2, PORT2,ISLIN2,MRES)
            motors.init_stages()
            return motors        
        """



class PowerControl(object):
        def __init__(self, PowerIP=None, PowerPort=None):
                self.Power = None
                if not (PowerIP and PowerPort):
                        print("Invalid power connection information.  No power control.")
                        self.PowerIP = None
                        self.PowerPort = None
                        self.coninfo = False
                else:
                        self.PowerIP = PowerIP
                        self.PowerPort = PowerPort
                        self.coninfo = True

        def setPower(self, enable=False):
                if not self.coninfo:
                        print("Invalid power connection information.  No power control.")
                elif self.coninfo and not self.Power:
                        if enable:
                                self.Power = Serial_TCPServer((self.PowerIP, self.PowerPort))
                        else:
                                print("Power already disabled.")
                elif self.coninfo and self.Power:
                        if not enable:
                                self.Power.sock.close()
                                self.Power = None
                        else:
                                print("Power already enabled.")
