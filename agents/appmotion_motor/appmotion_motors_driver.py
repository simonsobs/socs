##########################################################################
#
# Applied Motion Motor Control for UCSD
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
# https://appliedmotion.s3.amazonaws.com/Host-Command-Reference_920-0002W_0.pdf
#
##########################################################################


##########################################################################
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
# https://appliedmotion.s3.amazonaws.com/Host-Command-Reference_920-0002W_0.pdf
#
##########################################################################


import sys
from socs.agent.moxaSerial import Serial_TCPServer
from time import sleep
import numpy as np


# Time to wait for the user to power on the controllers and to see the
# power-on signature from the serial port
DEFAULT_WAIT_START_TIME = 15.0  # seconds

# Motor Names
MOTOR1 = 1
MOTOR2 = 2
ALL = 3

# Conversions for stages
# Conversion for the FTS Linear Stage - Check for factor of two later
AXIS_THREADS_PER_INCH_STAGE = 10.0
# Measured on stepper, Check for factor of two later
AXIS_THREADS_PER_INCH_XYZ = 10.0
# AXIS_THREADS_PER_INCH = 10.0 #Measured on stepper

class Motor:
    def __init__(self, ip, port, is_lin=True, name=None, index=None, m_res=False):
        self.ip = ip,
        self.port = port,
        self.is_lin = is_lin,
        self.name = name,
        self.motor = index,
        self.ser = Serial_TCPServer((ip, port)),
        
        self.pos = 0 #Position in counts (should always be integer)
        self.real_pos = 0.0 #Position in inches
        
        if not (ip and port):
            print("Invalid Motor information. No Motor control.")
            self.motor = None
        else:
            print('establishing serial server with motor!')
            self.motor = Serial_TCPServer((ip, port))
            if m_res == 'manual':
                self.res = 'manual'
                self.s_p_rev = 8000.0 # Steps per revolution (thread)
            else:
                self.res = 'default' # Corresponds to mapping above
                self.s_p_rev = 20000.0 # Steps per revolution (thread)
        
        if self.motor:
            # Check to make sure the device is in receive mode and reset if
            # necessary
            msg = self.writeread('RS\r')  # RS = Request Status
            self.flushInput()
            print(msg)
            if (msg == 'RS=R'):
                print("%s in receive mode." % (self.name))
            elif (msg != 'RS=R'):
                print(
                    "%s not in receive mode.  Resetting." %
                    (self.name))
                print("Message was: ", msg)
                self.kill_all_commands(self.motor)
                if (msg == 'RS=AR'):
                    amsg = self.writeread('AL\r')  # AL = Alarm Code
                    print('is message is: ', amsg)
                    print("Alarm was found. Resetting.")
                    self.write('AR\r')  # AR = Alarm Reset
                    self.flushInput()
                else:
                    print('Irregular message received.')
                    sys.exit(1)
                    
        if m_res:
            self.write('EG8000\r')  # EG = Electronic Gearing
            self.write('SA\r')  # SA = Save Parameters
            self.flushInput()
            sleep(0.1)
            msg = self.writeread('EG\r')
            self.flushInput()
            if (len(msg) <= 4):    # Need at least MR=X + \r, which is 5 characters
                print(
                    "Couldn't get microstep resolution for %s.  Assuming 8." %
                    (self.name))
            else:
                print(msg)
                ms_info = msg[3:]
                self.s_p_rev = float(ms_info)
        else:
            msg = self.writeread('EG\r')
            self.flushInput()
            if (len(msg) <= 4):
                print(
                    "Couldn't get microstep resolution for %s. Disconnect and retry." %
                    (self.name))
            else:
                print(msg)
                ms_info = msg[3:]
                self.s_p_rev = float(ms_info)
                ms_info = float(ms_info)

        if (self.motor is not None) and (self.is_lin):
            # DL1 = Define Limits for closed input (definition unclear in
            # manual, however)
            msg = self.writeread('DL\r')
            print(f"msg: {msg}")
            if msg != 'DL=2':
                print("Limits not defined as normally open. Resetting...")
                self.write('DL2\r')  # DL2 = Define Limits for open input
                sleep(0.1)
                self.flushInput()
            msg = self.writeread('CC\r')  # CC = Change Current
            print(msg)
            current = float(msg[3:])
            if current < 1.5:
                print("Operating current insufficient. Resetting...")
                self.write('CC1.5\r')
        else:
            if self.motor is not None:
                self.write('JE\r')  # JE = Jog Enable
                

    def is_moving(self, motor=ALL, verbose=False):
        """
        Returns True if either motor is moving, False if both motors
        are not moving. Also returns True if the motor provides an irregular
        status message, such as any alarm keys.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL. (default ALL)
            verbose (bool): Prints output from motor requests if True.
                (default False)
        """

        self.flushInput()
        # Get the status of the motor and print if verbose = True
        msg = self.writeread('RS\r')  # RS = Request Status
        name = self.name
        self.flushInput()
        if verbose:
            print(msg)
            sys.stdout.flush()
        # If either motor is moving, immediately return True
        if (msg == 'RS=FMR'):
            if verbose:
                print(f'Motor {name} is still moving.')
            return True
        elif (msg == 'RS=R'):
            if verbose:
                print(f'Motor {name} is not moving.')
                continue
        elif (msg == 'RS=AR'):
            if verbose:
                print(msg)
            # Check what the alarm message is
            msg = self.writeread('AL\r')
            if (msg == 'AL=0002'):
                print('CCW limit switch hit unexpectedly.')
                return True
            elif (msg == 'AL=0004'):
                print('CW limit switch hit unexpectedly.')
                return True
        else:
            print(f'Irregular error message for motor {name}: {msg}')
            return True
        if verbose:
            print('Neither motor is moving.')
        return False

    def move_off_limit(self, motor=ALL):
        """
        Ignores alarm to be able to move off the limit switch if 
        unexpectedly hit, and resets alarm. Function should be used when not
        able to move off limit switch due to alarm.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        mot_id = self.motor
        msg = self.writeread('AL\r')
        if (msg == 'AL=0002'):
            print(
                'CCW limit switch hit unexpectedly. Moving one inch away from switch.')
            self.move_axis_by_length(motor=mot_id, pos=1, pos_is_inches=True)
            sleep(3)
            self.reset_alarms(motor=mot_id)
        elif (msg == 'AL=0004'):
            print(
                'CW limit switch hit unexpectedly. Moving one inch away from switch.')
            self.move_axis_by_length(motor=mot_id, pos=-1, pos_is_inches=True)
            sleep(3)
            self.reset_alarms(motor=mot_id)
        else:
            print(f'Motor{motor} not on either switch')

    def home_with_limits(self, motor=ALL):
        """
        Uses the limit switches to zero all motor positions.
        This function should only be used if the linear stages do not have
        home switches, and should be done carefully. Does one motor at a time
        in order to be careful.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        
        if self.motor is None:
            print('Specified motor is invalid -- exiting function')
            return
        mot_id = self.motor
        # Basically, move motors until it hits the limit switch. This will
        # trigger an alarm
        self.move_axis_by_length(motor=mot_id, pos=-30, pos_is_inches=True)
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        
        moving = True
        while moving:
            msg = self.writeread('AL\r')
            # This is the error message for the limit switch near the motor
            if (msg == 'AL=0002'):
                print(
                    'Reached CCW limit switch. Moving 1 inch away from limit switch')
                pos = int(
                    1.0 *
                    AXIS_THREADS_PER_INCH_STAGE *
                    self.s_p_rev /
                    2.0)
                self.write('DI%i\r' % (pos))  # DI = Distance/Position
                self.write('FL\r')  # FL = Feed to Length
                self.flushInput()

                # Wait for motor to get off limit switch and reset alarms
                sleep(3)
                print('Resetting alarms')
                self.reset_alarms(motor=mot_id)

            if not self.is_moving(motor=mot_id):
                # zero motor and encoder
                print(f'Zeroing {motor}')
                sleep(1)
                self.set_zero(motor=mot_id)
                self.set_encoder_value(motor=mot_id)
                # move on to next stage
                moving = False
        print('Stage zeroed using limit switch')

    def start_jogging(self, motor=ALL):
        """
        Starts jogging control for specified motors.
    
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        
        if not self.motor:
            print("Specified motor is invalid - not starting jogging.")
            continue
        self.write('JE\r')  # JE = Jog Enable
        # WI = Wait for Input - Set into wait mode on empty input pin
        self.write('WI4L\r')
        self.flushInput()

    def stop_jogging(self, motor=ALL):
        """
        Stop jogging control to all motors.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        self.kill_all_commands(self.motor)

    def seek_home_linear_stage(self, motor=ALL):
        """
        Move the linear stage to its home position using the home 
        limit switch.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(self.motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        if not self.motor:
            print("Specified motor is invalid - no motion.")
            continue

        elif not self.is_lin:
            print("Motor isn't connected to a linear stage.")
            continue
        self.write('VE2.0\r')  # VE = Velocity
        self.write('AC2.0\r')  # AC = Acceleration Rate
        self.write('DE2.0\r')  # DE = Deceleration
        self.write('DI-1\r')  # DI = Distance/Position (sets direction)
        self.write('SHX3L\r')  # SH = Seek Home
        self.flushInput()
        print("Linear stage homing...")
        self.block_while_moving(self.motor, verbose=True)

        print("Linear stage home found.")

    def set_zero(self, motor=ALL):
        """
        Tell the motor to set the current position as the zero 
        point.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(self.motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        if not self.motor:
            print("Specified motor is invalid.")
            continue
        self.pos = 0
        self.real_pos = 0.0
        self.write('SP0\r')  # SP = Set Position
        self.flushInput()

    def get_position(self, motor=ALL):
        """
        Get the position of the motor in counts, relative to the set
        zero point (or starting point).

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)

        Returns:
            positions (list): The positions in counts of the specified motors.
        """
        positions = []
        if not self.motor:
            print("Specified motor is invalid - no position info.")
            positions.append(None)
        else:
            positions.append(self.pos)
        return positions

    def get_position_in_inches(self, motor=ALL):
        """
        Get the position of the motor in inches, relative to the set
        zero point (or starting point).

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)

        Returns:
            real_positions (list): The positions in inches of the specified
            motors.
        """
        real_positions = []
        if not self.motor:
            print("Specified motor is invalid - no position info.")
            real_positions.append(None)
        else:
            real_positions.append(self.real_pos)
        return real_positions

    def get_immediate_position(self, motor=ALL, inches=True):
        """
        Get the position of the motor while it is currently in 
        motion. An estimate based on the calculated trajectory of the movement,
        relative to the zero point.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            inches (bool): Whether the returned position should be in units of
                inches or not.

        Returns:
            positions (list): The positions of each motor, in either inches or
                counts.

        """
        positions = []
        counts_to_inches = 100000  # empirically, 100,000 counts per inch

        if not self.motor:
            print("Specified motor is invalid - no encoder info.")
            continue
        # Check that the motor position output is in the right mode
        msg = self.writeread('IF\r')
        if msg == 'IF=H':
            # Output is coming out in hexadecimal, switching to decimal
            print('Changing output to decimal')
            self.writeread('IFD\r')

        i_pos = self.writeread('IP\r')
        sleep(0.1)
        self.flushInput()
        i_pos = int(i_pos.rstrip('\r')[3:])
        if inches:
            i_pos = i_pos / counts_to_inches
        positions.append(i_pos)

        return positions

    def move_axis_to_position(
            self,
            motor=MOTOR1,
            pos=0,
            pos_is_inches=False,
            lin_stage=True):
        """
        Move the axis to the given absolute position in counts or
        inches.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL. (default MOTOR1)
            pos (float): The desired position in counts or in inches, positive
                indicates away from the motor. (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts. (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not. (default True)
        """
        if not self.motor:
            print("Specified motor is invalid - no motion.")
            continue
        # Set the threads per inch based on if the motor controls the FTS
        # linear stage
        if lin_stage:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
        else:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

        # Convert from inches if necessary
        if(pos_is_inches):
            # 2.0 is because threads go twice the distance for one
            # revolution
            unit_pos = int(pos * AXIS_THREADS_PER_INCH *
                          self.s_p_rev / 2.0)
        else:
            unit_pos = int(pos)
        # Set the new pos and real_pos parameters of the motor object
        self.pos = unit_pos
        self.real_pos = 2.0 * unit_pos / \
            (AXIS_THREADS_PER_INCH * self.s_p_rev)  # See 2.0 note above
        # Move the motor
        self.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
        self.write('FP\r')  # FL = Feed to Position
        self.flushInput()

    def move_axis_by_length(
            self,
            motor=MOTOR1,
            pos=0,
            pos_is_inches=False,
            lin_stage=True):
        """
        Move the axis relative to the current position by the 
        specified number of counts or inches.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default MOTOR1)
            pos (float): the desired number of counts or inches to move from
                current position, positive indicates away from the motor.
                (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts. (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not. (default True)
        """
        if not self.motor:
            print("Specified motor is invalid - no motion.")
            continue
        # Set the threads per inch based on if the motor controls the FTS
        # linear stage
        if lin_stage:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
        else:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

        # Convert from inches if necessary
        if(pos_is_inches):
            unit_pos = int(
                pos *
                AXIS_THREADS_PER_INCH *
                self.s_p_rev /
                2.0)  # See 2.0 note above
        else:
            unit_pos = int(pos)

        # Set the new pos and real_pos parameters of the motor object
        self.pos += unit_pos
        self.real_pos += 2.0 * unit_pos / \
            (AXIS_THREADS_PER_INCH * self.s_p_rev)  # See 2.0 note above

        # Move the motor
        self.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
        self.write('FL\r')  # FL = Feed to Length
        self.flushInput()
        print("Final position: ", pos)

    def set_velocity(self, motor=ALL, velocity=1.0):
        """
        Set velocity in revolutions/second.  Range is 0.25 - 50.
        Accepts floating point values.

        Parameters:
            motor(int): MOTOR1, MOTOR2, or ALL. (default ALL)
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 1.0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(self.motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        if not self.motor:
            print("Specified motor is invalid - no velocity set.")
            continue
        self.write('VE%1.3f\r' % (velocity))  # VE = Velocity
        self.flushInput()

    def set_acceleration(self, motor=ALL, accel=5):
        """
        Set acceleration of motors driving stages. (default 5)
        .. note::
            `accel` parameter will only accept integer values.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL. (default ALL)
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 5)
        """
        if not self.motor:
            print("Specified motor is invalid - no acceleration set.")
            continue
        self.write('AC%i\r' % (accel))  # AC = Acceleration Rate
        self.write('DE%i\r' % (accel))  # DE = Deceleration
        self.flushInput()

    def kill_all_commands(self, motor=ALL):
        """
        Stop all active commands on the device.
        Parameters:
            motor(int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        if not self.motor:
            print("Specified motor is invalid - no motion.")
            continue
        # SK = Stop & Kill - Stop/kill all commands, turn off waiting for
        # input
        self.write('SK\r')
        self.flushInput()

    def block_while_moving(self, motor=ALL, update_period=.1, verbose=False):
        """
        Block until the specified axes have stop moving. Checks each
        axis every update_period seconds.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            update_period (float): Time after which to check each motor in
                seconds. (default .1)
            verbose (bool): Prints output from motor requests if True.
                (default False)
        """
        self.flushInput()
        msg = self.writeread('RS\r')
        count = 0
        while(msg != 'RS=R'):
            count += 1
            self.flushInput()
            # Get the status of the motor and print if verbose = True
            msg = self.writeread('RS\r')  # RS = Request Status
            self.flushInput()
            if verbose:
                print(msg)
                sys.stdout.flush()
            # Remove the motor from m_list (so that the while loop
            # continues) only if the status is not "Ready"

            # Break if too many while loop iterations - indicates potential
            # problem
            if count > 2000:
                print(
                    'Motion taking too long, there may be a different failure or alarm...')
                break

            # Wait the specified amount of time before rechecking the status
            sleep(update_period)
        print('')

    def run_positions(self, pos_data, motor=ALL, pos_is_inches=False):
        """
        Runs a list of entries as positions. For
        motor=ALL, the first column must be the x-data, and the second column
        the y-data. Each position will be attained.

        Parameters:
            pos_data (list): Tab-delimited list of entries. First column
                is x-data, second column is y-data.
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(self.motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        if (len(pos_data) > 0):
            # This is for the 2-axis case.  In the 1-axis case, pos_data[0] will
            # just be a floating point value
            if motor == ALL and len(pos_data) < 2:
                raise Exception(
                    "You specified that both axes would be moving, but didn't provide data for both.")

        if motor == ALL:
            self.move_axis_to_position(
                MOTOR1, pos_data[0], pos_is_inches=pos_is_inches)
            self.move_axis_to_position(
                MOTOR2, pos_data[1], pos_is_inches=pos_is_inches)
        elif motor == MOTOR1:
            self.move_axis_to_position(MOTOR1, pos_data, pos_is_inches=pos_is_inches)
        elif motor == MOTOR2:
            self.move_axis_to_position(MOTOR2, pos_data, pos_is_inches=pos_is_inches)

        print(f'Moving position to {pos_data}')

    def set_motor_enable(self, motor=ALL, enable=True):
        """
        Set motor enable to true or false for given axis. Should
        disable motor when stopped for lower noise data acquisition.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            enable (bool): Enables specified motor if True, disables specified
                motor if False.
        """
        if not self.motor:
            print("Specified motor is invalid - cannot enable.")
            continue
        if enable:
            self.write('ME\r')  # ME = Motor Enable
        else:
            self.write('MD\r')  # MD = Motor Disable
        self.flushInput()

    def retrieve_encoder_info(self, motor=ALL):
        """
        Retrieve all motor step counts to verify movement.
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        move_status = self.is_moving(self.motor)
        e_positions = []

        # If the motors are moving, return NaNs to keep from querying the
        # motor controllers during motion.
        if move_status:
            e_positions.append(np.nan)
            return e_positions

        if not self.motor:
            print("Specified motor is invalid - no encoder info.")
            continue
        e_pos = self.writeread('EP\r')  # EP = Encoder Position
        sleep(0.1)
        self.flushInput()
        e_pos = int(e_pos.rstrip('\r')[3:])
        e_positions.append(e_pos)

        return e_positions

    def set_encoder_value(self, motor=ALL, value=0):
        """
        Set the encoder values in order to keep track of absolute
        position.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            value (float): Sets encoder value. (default 0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(self.motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        e_positions = []
        if not self.motor:
            print("Specified motor is invalid - encoder value not set.")
            continue
        # Set the motor position
        e_pos_set = self.write('EP%i\r' % (value))  # EP = Encoder Position
        sleep(0.1)
        self.flushInput()
        # Read and return the new motor position
        e_pos = self.writeread('EP\r')  # EP = Encoder Position
        sleep(0.1)
        self.flushInput()
        e_pos = int(e_pos.rstrip('\r')[3:])
        print(e_pos)
        e_positions.append(e_pos)
        
        return e_positions

    def start_rotation(self, motor=MOTOR2, velocity=12.0, rot_accel=1.0):
        """
        Starts jogging specifically for the rotation of the output
        polarizer in the FTS.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default MOTOR2)
            velocity (float): The rotation velocity in revolutions per second (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000].  (default 1.0)
        """
        if not self.motor:
            print("Specified motor is invalid - not starting jogging.")
            continue

        # Set the jog parameters
        self.write('JS%1.3f\r' % (velocity))  # JS = Jog Speed
        self.write('JA%i\r' % (rot_accel))  # JA = Jog Acceleration
        self.write('JL%i\r' % (rot_accel))  # JL = Jog Decel

        # Start rotation
        self.write('CJ\r')  # CJ = Commence Jogging
        self.flushInput()

    def stop_rotation(self, motor=MOTOR2):
        """
        Stops jogging for the rotation of the specified motor.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default MOTOR2)
        """
        if not self.motor:
            print("Specified motor is invalid.")
            continue
        self.write('SJ\r')  # SJ = Stop Jogging
        self.flushInput()

    def reset_alarms(self, motor=ALL):
        """
        Resets alarm codes present. Only advised if you have checked
        what the alarm is first!

        Parameters:
        motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        if not self.motor:
            print("Specified motor is invalid.")
            continue
        self.write('AR\r')
        self.flushInput()

    def close_connection(self, motor=ALL):
        """
        Close the connection to the serial controller for the
        specified motor.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        if not self.motor:
            print("Specified motor is invalid - no connection to close.")
            continue
        self.sock.close()
        print("Connection to serial controller disconnected.")

#NEED TO FIX
#    def reconnect_motor(self, motor=ALL):
#        """
#        Reestablish connection with specified motor.
#        
#        Parameters:
#            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
#        """
#        if not self.motor:
#            print("Specified motor is invalid - no connection to close.")
#            continue
#        print(f"port: {self.port}")
#        try:
#            self.sock.connect(self.port) #return 1
#            print(f"Connection with motor{motor} has been reestablished.")
#            sock_status = 1
#        except:
#            print(f"Connection with motor{motor} could not be reestablished.") #return 0
#            sock_status = 0        

