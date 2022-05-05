##########################################################################
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


class MotControl(object):
    """
    Driver for connecting to the SAT1 XY Stages. Differs from LATRt agent in 
    that motors/controllers are seen as arguments.
    Motor1 can be the X axis OR the Y axis, same with Motor2. Depends on setup 
    (ip address + port).

    Args:
        motor1_ip (str) : the IP address associated with Motor1
        motor1_port (int) : the port address associated with Motor1.
        motor1_is_lin (bool) : Boolean that determines if Motor1 is a linear 
            motor.
        motor2_ip (str) : the IP address associated with Motor2
        motor2_port (int) : the port address associated with Motor2
        motor2_is_lin (bool) : Boolean that determines if Motor2 is a linear 
            motor.
        mode: 'acq' : Start data acquisition on initialize
        m_res (bool) : True if manual resolution, False if default (res=8)
    """

    def __init__(
            self,
            motor1_ip=None,
            motor1_port=None,
            motor1_is_lin=True,
            motor2_ip=None,
            motor2_port=None,
            motor2_is_lin=True,
            m_res=False):
        """
        Initialize a MotControl object.

        Parameters:
            motor1_ip (str) : the IP address associated with Motor1
            motor1_port (int) : the port address associated with Motor1
            motor2_ip (str) : the IP address associated with Motor2
            motor2_port (int) : the port address associated with Motor2
            m_res (bool) : True if manual resolution, False if default (res=8) 
        """

        # Set up the connection to the first motor
        # Initialized so that the startup position is set to zero
        if not (motor1_ip and motor1_port):
            print("Invalid Motor 1 information.  No Motor 1 control.")
            self.motor1 = None
        else:
            print('establishing serial server with motor1!')
            self.motor1 = Serial_TCPServer((motor1_ip, motor1_port))
            if m_res:
                self.motor1.res = 'manual'
                self.motor1.s_p_rev = 8000.0 # Steps per revolution (thread)
            else:
                self.motor1.res = '8' # Corresponds to mapping above
                self.motor1.s_p_rev = 20000.0 # Steps per revolution (thread)
            self.motor1.name = 'motor1'
            self.motor1.motor = MOTOR1
            self.motor1.pos = 0 # Position in counts (should always be an integer)
            self.motor1.real_pos = 0.0 # Position in inches
            self.motor1.is_lin = motor1_is_lin
                
        # Set up the connection to the second motor
        # Initialized so that the startup position is set to zero
        if not (motor2_ip and motor2_port):
            print("Invalid Motor 2 information.  No Motor 2 control.")
            self.motor2 = None
        else:
            print('establishing serial server with motor2!')
            self.motor2 = Serial_TCPServer((motor2_ip, motor2_port))
            if m_res:
                self.motor2.res = 'manual'
                self.motor2.s_p_rev = 8000.0 # Steps per revolution (thread)
            else:
                self.motor2.res = '8' # Corresponds to mapping above
                self.motor2.s_p_rev = 20000.0 # Steps per revolution (thread)
            self.motor2.name = 'motor2'
            self.motor2.motor = MOTOR2
            self.motor2.pos = 0 # Position in counts
            self.motor2.real_pos = 0.0  Position in inches
            self.motor2.is_lin = motor2_is_lin

        for motor in ([self.motor1, self.motor2]):
            if motor:
                # Check to make sure the device is in receive mode and reset if
                # necessary
                msg = motor.writeread('RS\r')  # RS = Request Status
                motor.flushInput()
                print(msg)
                if (msg == 'RS=R'):
                    print("%s in receive mode." % (motor.name))
                elif (msg != 'RS=R'):
                    print(
                        "%s not in receive mode.  Resetting." %
                        (motor.name))
                    print("Message was: ", msg)
                    self.kill_all_commands(motor.motor)
                    if (msg == 'RS=AR'):
                        amsg = motor.writeread('AL\r')  # AL = Alarm Code
                        print('is message is: ', amsg)
                        print("Alarm was found. Resetting.")
                        motor.write('AR\r')  # AR = Alarm Reset
                        motor.flushInput()
                    else:
                        print('Irregular message received.')
                        sys.exit(1)

                # Check the microstep resolution
                if m_res:
                    motor.write('EG8000\r')  # EG = Electronic Gearing
                    motor.write('SA\r')  # SA = Save Parameters
                    motor.flushInput()
                    sleep(0.1)
                    msg = motor.writeread('EG\r')
                    motor.flushInput()
                    if (len(msg) <= 4):    # Need at least MR=X + \r, which is 5 characters
                        print(
                            "Couldn't get microstep resolution for %s.  Assuming 8." %
                            (motor.name))
                    else:
                        print(msg)
                        ms_info = msg[3:]
                        motor.s_p_rev = float(ms_info)
                else:
                    msg = motor.writeread('EG\r')
                    motor.flushInput()
                    if (len(msg) <= 4):
                        print(
                            "Couldn't get microstep resolution for %s. Disconnect and retry." %
                            (motor.name))
                    else:
                        print(msg)
                        ms_info = msg[3:]
                        motor.s_p_rev = float(ms_info)
                        ms_info = float(ms_info)
            if (motor is not None) and (motor.is_lin):
                # DL1 = Define Limits for closed input (definition unclear in
                # manual, however)
                msg = motor.writeread('DL\r')
                print(f"msg: {msg}")
                if msg != 'DL=2':
                    print("Limits not defined as normally open. Resetting...")
                    motor.write('DL2\r')  # DL2 = Define Limits for open input
                    sleep(0.1)
                    motor.flushInput()
                msg = motor.writeread('CC\r')  # CC = Change Current
                print(msg)
                current = float(msg[3:])
                if current < 1.5:
                    print("Operating current insufficient. Resetting...")
                    motor.write('CC1.5\r')
            else:
                if motor is not None:
                    motor.write('JE\r')  # JE = Jog Enable

    def gen_motor_list(self, motor):
        """gen_motor_list(motor=ALL):
        
        **Task** - Generate a list of the motors in a MotControl object.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL

        Returns:
            m_list (list): List of desired motors.
        """
        m_list = []
        if motor == MOTOR1 or motor == ALL:
            m_list.append(self.motor1)
        if motor == MOTOR2 or motor == ALL:
            m_list.append(self.motor2)
        return m_list

    def is_moving(self, motor=ALL, verbose=False):
        """is_moving(motor=ALL, verbose=False):
        
        **Task** - Returns True if either motor is moving, False if both motors
        are not moving. Also returns True if the motor provides an irregular
        status message, such as any alarm keys.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL. (default ALL)
            verbose (bool): Prints output from motor requests if True. 
                (default False)
        """
        m_list = self.gen_motor_list(motor)

        for motor in (m_list):
            motor.flushInput()
            # Get the status of the motor and print if verbose = True
            msg = motor.writeread('RS\r')  # RS = Request Status
            name = motor.name
            motor.flushInput()
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
                msg = motor.writeread('AL\r')
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
        """move_off_limit(motor=ALL):
        
        **Task** -Ignores alarm to be able to move off the limit switch if 
        unexpectedly hit, and resets alarm. Function should be used when not
        able to move off limit switch due to alarm.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        m_list = self.gen_motor_list(motor)

        for motor in (m_list):
            mot_id = motor.motor
            msg = motor.writeread('AL\r')
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
        """home_with_limits(motor=ALL):
        
        **Task** - Uses the limit switches to zero all motor positions.
        This function should only be used if the linear stages do not have
        home switches, and should be done carefully. Does one motor at a time
        in order to be careful.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        m_list = self.gen_motor_list(motor)

        for motor in (m_list):
            if motor is None:
                print('Specified motor is invalid -- exiting function')
                return
            mot_id = motor.motor
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
                msg = motor.writeread('AL\r')
                # This is the error message for the limit switch near the motor
                if (msg == 'AL=0002'):
                    print(
                        'Reached CCW limit switch. Moving 1 inch away from limit switch')
                    pos = int(
                        1.0 *
                        AXIS_THREADS_PER_INCH_STAGE *
                        motor.s_p_rev /
                        2.0)
                    motor.write('DI%i\r' % (pos))  # DI = Distance/Position
                    motor.write('FL\r')  # FL = Feed to Length
                    motor.flushInput()

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
        """start_jogging(motor=ALL):
        
        **Task** - Starts jogging control for specified motors.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - not starting jogging.")
                continue
            motor.write('JE\r')  # JE = Jog Enable
            # WI = Wait for Input - Set into wait mode on empty input pin
            motor.write('WI4L\r')
            motor.flushInput()

    def stop_jogging(self, motor=ALL):
        """stop_jogging(motor=ALL):
        
        **Task** - Stop jogging control to all motors.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        self.kill_all_commands(motor)

    def seek_home_linear_stage(self, motor=ALL):
        """seek_home_linear_stage(motor=ALL):
        
        **Task** - Move the linear stage to its home position using the home 
        limit switch.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no motion.")
                continue

            elif not motor.is_lin:
                print("Motor isn't connected to a linear stage.")
                continue
            motor.write('VE2.0\r')  # VE = Velocity
            motor.write('AC2.0\r')  # AC = Acceleration Rate
            motor.write('DE2.0\r')  # DE = Deceleration
            motor.write('DI-1\r')  # DI = Distance/Position (sets direction)
            motor.write('SHX3L\r')  # SH = Seek Home
            motor.flushInput()
            print("Linear stage homing...")
            self.block_while_moving(motor.motor, verbose=True)

        print("Linear stage home found.")

    def set_zero(self, motor=ALL):
        """set_zero(motor=ALL):
        
        **Task** - Tell the motor to set the current position as the zero 
        point.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid.")
                continue
            motor.pos = 0
            motor.real_pos = 0.0
            motor.write('SP0\r')  # SP = Set Position
            motor.flushInput()

    def get_position(self, motor=ALL):
        """get_position(motor=ALL):
        
        **Task** - Get the position of the motor in counts, relative to the set
        zero point (or starting point).

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)

        Returns:
            positions (list): The positions in counts of the specified motors.
        """
        m_list = self.gen_motor_list(motor)
        positions = []
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid - no position info.")
                positions.append(None)
            else:
                positions.append(motor.pos)
        return positions

    def get_position_in_inches(self, motor=ALL):
        """get_position_in_inches(motor=ALL):
        
        **Task** - Get the position of the motor in inches, relative to the set
        zero point (or starting point).

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)

        Returns:
            real_positions (list): The positions in inches of the specified 
            motors.
        """
        m_list = self.gen_motor_list(motor)
        real_positions = []
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid - no position info.")
                real_positions.append(None)
            else:
                real_positions.append(motor.real_pos)
        return real_positions

    def get_immediate_position(self, motor=ALL, inches=True):
        """get_immediate_positions(motor=ALL, inches=True):
        
        **Task** - Get the position of the motor while it is currently in 
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
        m_list = self.gen_motor_list(motor)
        positions = []

        counts_to_inches = 100000  # empirically, 100,000 counts per inch

        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no encoder info.")
                continue
            # Check that the motor position output is in the right mode
            msg = motor.writeread('IF\r')
            if msg == 'IF=H':
                # Output is coming out in hexadecimal, switching to decimal
                print('Changing output to decimal')
                motor.writeread('IFD\r')

            i_pos = motor.writeread('IP\r')
            sleep(0.1)
            motor.flushInput()
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
        """move_axis_to_position(motor=MOTOR1, pos=0, pos_is_inches=False,
            lin_stage=True):
        
        **Task** - Move the axis to the given absolute position in counts or
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

        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
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
                              motor.s_p_rev / 2.0)
            else:
                unit_pos = int(pos)

            # Set the new pos and real_pos parameters of the motor object
            motor.pos = unit_pos
            motor.real_pos = 2.0 * unit_pos / \
                (AXIS_THREADS_PER_INCH * motor.s_p_rev)  # See 2.0 note above

            # Move the motor
            motor.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
            motor.write('FP\r')  # FL = Feed to Position
            motor.flushInput()

    def move_axis_by_length(
            self,
            motor=MOTOR1,
            pos=0,
            pos_is_inches=False,
            lin_stage=True):
        """move_axis_by_length(motor=MOTOR1, pos=0, pos_is_inches=0, 
            lin_stage=0):
            
        **Task** - Move the axis relative to the current position by the 
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

        m_list = self.gen_motor_list(motor)
        for motor in m_list:
            if not motor:
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
                    motor.s_p_rev /
                    2.0)  # See 2.0 note above
            else:
                unit_pos = int(pos)

            # Set the new pos and real_pos parameters of the motor object
            motor.pos += unit_pos
            motor.real_pos += 2.0 * unit_pos / \
                (AXIS_THREADS_PER_INCH * motor.s_p_rev)  # See 2.0 note above

            # Move the motor
            motor.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
            motor.write('FL\r')  # FL = Feed to Length
            motor.flushInput()
            print("Final position: ", pos)

    def set_velocity(self, motor=ALL, velocity=1.0):
        """set_velocity(motor=ALL, velocity=1.0):
        
        **Task** - Set velocity in revolutions/second.  Range is 0.25 - 50. 
        Accepts floating point values.
        
        Parameters:
            motor(int): MOTOR1, MOTOR2, or ALL. (default ALL)
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 1.0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no velocity set.")
                continue
            motor.write('VE%1.3f\r' % (velocity))  # VE = Velocity
            motor.flushInput()

    def set_acceleration(self, motor=ALL, accel=5):
        """set_acceleration(motor=ALL, accel=5):
        
        **Task** - Set acceleration of motors driving stages. (default 5)
        
        .. note::
            `accel` parameter will only accept integer values.
            
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL. (default ALL)
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 5)
        """
        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no acceleration set.")
                continue
            motor.write('AC%i\r' % (accel))  # AC = Acceleration Rate
            motor.write('DE%i\r' % (accel))  # DE = Deceleration
            motor.flushInput()

    def kill_all_commands(self, motor=ALL):
        """kill_all_commands(motor=ALL):
        
        **Task** - Stop all active commands on the device.
        
        Parameters:
            motor(int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no motion.")
                continue
            # SK = Stop & Kill - Stop/kill all commands, turn off waiting for
            # input
            motor.write('SK\r')
            motor.flushInput()

    def block_while_moving(self, motor=ALL, update_period=.1, verbose=False):
        """block_while_moving(motor=ALL, update_period=.1, verbose=False):
        
        **Task** - Block until the specified axes have stop moving. Checks each
        axis every update_period seconds.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            update_period (float): Time after which to check each motor in
                seconds. (default .1)
            verbose (bool): Prints output from motor requests if True.
                (default False)
        """
        m_list = self.gen_motor_list(motor)
        count = 0
        while(m_list):
            count += 1
            for motor in (m_list):
                motor.flushInput()
                # Get the status of the motor and print if verbose = True
                msg = motor.writeread('RS\r')  # RS = Request Status
                motor.flushInput()
                if verbose:
                    print(msg)
                    sys.stdout.flush()
                # Remove the motor from m_list (so that the while loop
                # continues) only if the status is not "Ready"
                if(msg == 'RS=R'):
                    m_list.remove(motor)  # Should only be in the list once

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
        """run_positions(pos_data=[1,1], motor=ALL, pos_is_inches=False):
        
        **Task** - Runs a tab-delimited list of entries as positions. For 
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
        move_status = self.is_moving(motor)
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
        """set_motor_enable(motor=ALL, enable=True):
        
        **Task** - Set motor enable to true or false for given axis. Should
        disable motor when stopped for lower noise data acquisition.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            enable (bool): Enables specified motor if True, disables specified
                motor if False.
        """
        m_list = self.gen_motor_list(motor)
        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - cannot enable.")
                continue
            if enable:
                motor.write('ME\r')  # ME = Motor Enable
            else:
                motor.write('MD\r')  # MD = Motor Disable
            motor.flushInput()

    def retrieve_encoder_info(self, motor=ALL):
        """retrieve_encoder_info(motor=ALL):
        
        **Task** - Retrieve all motor step counts to verify movement.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        move_status = self.is_moving(motor)
        m_list = self.gen_motor_list(motor)
        e_positions = []

        # If the motors are moving, return NaNs to keep from querying the
        # motor controllers during motion.
        if move_status:
            for motor in m_list:
                e_positions.append(np.nan)
            return e_positions

        for motor in (m_list):
            if not motor:
                print("Specified motor is invalid - no encoder info.")
                continue
            e_pos = motor.writeread('EP\r')  # EP = Encoder Position
            sleep(0.1)
            motor.flushInput()
            e_pos = int(e_pos.rstrip('\r')[3:])
            e_positions.append(e_pos)

        return e_positions

    def set_encoder_value(self, motor=ALL, value=0):
        """set_encoder_value(motor=ALL, value=0):
        
        **Task** - Set the encoder values in order to keep track of absolute 
        position.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
            value (float): Sets encoder value. (default 0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving(motor)
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        m_list = self.gen_motor_list(motor)
        e_positions = []
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid - encoder value not set.")
                continue
            # Set the motor position
            e_pos_set = motor.write('EP%i\r' % (value))  # EP = Encoder Position
            sleep(0.1)
            motor.flushInput()
            # Read and return the new motor position
            e_pos = motor.writeread('EP\r')  # EP = Encoder Position
            sleep(0.1)
            motor.flushInput()
            e_pos = int(e_pos.rstrip('\r')[3:])
            print(e_pos)
            e_positions.append(e_pos)
        return e_positions

    def start_rotation(self, motor=MOTOR2, velocity=12.0, rot_accel=1.0):
        """start_rotation(motor=MOTOR2, velocity=12.0, rot_accel=1.0):
        
        **Task** - Starts jogging specifically for the rotation of the output
        polarizer in the FTS.

        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default MOTOR2)
            velocity (float): The rotation velocity in revolutions per second (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000].  (default 1.0)
        """
        m_list = self.gen_motor_list(motor)
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid - not starting jogging.")
                continue

            # Set the jog parameters
            motor.write('JS%1.3f\r' % (velocity))  # JS = Jog Speed
            motor.write('JA%i\r' % (rot_accel))  # JA = Jog Acceleration
            motor.write('JL%i\r' % (rot_accel))  # JL = Jog Decel

            # Start rotation
            motor.write('CJ\r')  # CJ = Commence Jogging
            motor.flushInput()

    def stop_rotation(self, motor=MOTOR2):
        """stop_rotation(motor=MOTOR2):
        
        **Task** - Stops jogging for the rotation of the specified motor.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default MOTOR2)
        """
        m_list = self.gen_motor_list(motor)
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid.")
                continue
            motor.write('SJ\r')  # SJ = Stop Jogging
            motor.flushInput()

    def reset_alarms(self, motor=ALL):
        """reset_alarms(motor=ALL):
        
        **Task** - Resets alarm codes present. Only advised if you have checked
        what the alarm is first!

        Parameters:
        motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """

        m_list = self.gen_motor_list(motor)
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid.")
                continue
            motor.write('AR\r')
            motor.flushInput()

    def close_connection(self, motor=ALL):
        """close_connection(motor=ALL):
        
        **Task** - Close the connection to the serial controller for the
        specified motor.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        m_list = self.gen_motor_list(motor)
        for motor in m_list:
            if not motor:
                print("Specified motor is invalid - no connection to close.")
                continue
            motor.sock.close()
        print("Connection to serial controller disconnected.")

    def reconnect_motor(self, motor=ALL):
        """reconnect_motor(motor=ALL):
        
        **Task** - Reestablish connection with specified motor.
        
        Parameters:
            motor (int): MOTOR1, MOTOR2, or ALL (default ALL)
        """
        m_list = self.gen_motor_list(motor)
        for mot in m_list:
            if not mot:
                print("Specified motor is invalid - no connection to close.")
                continue
            print(f"port: {mot.port}")
            try:
                mot.sock.connect(mot.port)
            except:
                print(f"Connection with motor{motor} could not be reestablished.")
        print(f"Connection with motor{motor} has been reestablished.")


