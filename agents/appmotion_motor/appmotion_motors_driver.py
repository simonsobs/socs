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
    def __init__(self, ip, port, is_lin=True, mot_id=None, index=None, m_res=False):
        self.ip = ip
        self.port = port
        self.is_lin = is_lin
        self.mot_id = mot_id
        self.motor = index
        self.ser = Serial_TCPServer((ip, port))

        self.pos = 0  # Position in counts (should always be integer)
        self.real_pos = 0.0  # Position in inches
        self.sock_status = 0

        if not (ip and port):
            print("Invalid Motor information. No Motor control.")
            self.ser = None
        else:
            print('establishing serial server with motor!')
            self.ser
            if m_res:
                self.res = 'manual'
                self.s_p_rev = 8000.0  # Steps per revolution (thread)
            else:
                self.res = 'default'  # Corresponds to mapping above
                self.s_p_rev = 20000.0  # Steps per revolution (thread)

        if self.ser:
            # Check to make sure the device is in receive mode and reset if
            # necessary
            msg = self.ser.writeread('RS\r')  # RS = Request Status
            self.ser.flushInput()
            print(msg)
            if (msg == 'RS=R'):
                print("%s in receive mode." % (self.mot_id))
            elif (msg != 'RS=R'):
                print(
                    "%s not in receive mode.  Resetting." %
                    (self.mot_id))
                print("Message was: ", msg)
                self.kill_all_commands()
                if (msg == 'RS=AR'):
                    amsg = self.ser.writeread('AL\r')  # AL = Alarm Code
                    print('is message is: ', amsg)
                    print("Alarm was found. Resetting.")
                    self.ser.write('AR\r')  # AR = Alarm Reset
                    self.ser.flushInput()
                else:
                    print('Irregular message received.')
                    sys.exit(1)

        if m_res:
            self.ser.write('EG8000\r')  # EG = Electronic Gearing
            self.ser.write('SA\r')  # SA = Save Parameters
            self.ser.flushInput()
            sleep(0.1)
            msg = self.ser.writeread('EG\r')
            self.ser.flushInput()
            if (len(msg) <= 4):    # Need at least MR=X + \r, which is 5 characters
                print(
                    "Couldn't get microstep resolution for %s.  Assuming 8,000." %
                    (self.mot_id))
            else:
                print(msg)
                ms_info = msg[3:]
                self.s_p_rev = float(ms_info)
        else:
            msg = self.ser.writeread('EG\r')
            self.ser.flushInput()
            if (len(msg) <= 4):
                print(
                    "Couldn't get microstep resolution for %s. Disconnect and retry." %
                    (self.mot_id))
            else:
                print(msg)
                ms_info = msg[3:]
                self.s_p_rev = float(ms_info)
                ms_info = float(ms_info)

        if (self.ser is not None) and (self.is_lin):
            # DL1 = Define Limits for closed input (definition unclear in
            # manual, however)
            msg = self.ser.writeread('DL\r')
            print(f"msg: {msg}")
            if msg != 'DL=2':
                print("Limits not defined as normally open. Resetting...")
                self.ser.write('DL2\r')  # DL2 = Define Limits for open input
                sleep(0.1)
                self.ser.flushInput()
            msg = self.ser.writeread('CC\r')  # CC = Change Current
            print(msg)
            current = float(msg[3:])
            if current < 1.5:
                print("Operating current insufficient. Resetting...")
                self.ser.write('CC1.5\r')
        else:
            if self.ser is not None:
                self.ser.write('JE\r')  # JE = Jog Enable

    def is_moving(self, verbose=True):
        """
        Returns True if either motor is moving, False if both motors
        are not moving. Also returns True if the motor provides an irregular
        status message, such as any alarm keys.

        Parameters:
            verbose (bool): Prints output from motor requests if True.
                (default False)
        """
        self.ser.flushInput()
        # Get the status of the motor and print if verbose = True
        print(f'*************\n Driver: is_moving for motor: {self.motor}\n***********')
        msg = self.ser.writeread('RS\r')  # RS = Request Status
        self.ser.flushInput()
        if verbose:
            print(f'verbose; message: {msg}')
            sys.stdout.flush()
        # If either motor is moving, immediately return True
        if (msg == 'RS=FMR'):
            if verbose:
                print(f'Motor {self.mot_id} is still moving.')
            return True
        elif (msg == 'RS=R'):
            if verbose:
                print(f'Motor {self.mot_id} is not moving.')
        elif (msg == 'RS=AR'):
            if verbose:
                print(msg)
            # Check what the alarm message is
            msg = self.ser.writeread('AL\r')
            if (msg == 'AL=0002'):
                print('CCW limit switch hit unexpectedly.')
                return True
            elif (msg == 'AL=0004'):
                print('CW limit switch hit unexpectedly.')
                return True
        else:
            print(f'Irregular error message for motor {self.mot_id}: {msg}')
            return True

    def move_off_limit(self):
        """
        Ignores alarm to be able to move off the limit switch if
        unexpectedly hit, and resets alarm. Function should be used when not
        able to move off limit switch due to alarm.

        """
        msg = self.ser.writeread('AL\r')
        if (msg == 'AL=0002'):
            print(
                'CCW limit switch hit unexpectedly. Moving one inch away from switch.')
            self.move_axis_by_length(pos=1, pos_is_inches=True)
            sleep(3)
            self.reset_alarms()
        elif (msg == 'AL=0004'):
            print(
                'CW limit switch hit unexpectedly. Moving one inch away from switch.')
            self.move_axis_by_length(pos=-1, pos_is_inches=True)
            sleep(3)
            self.reset_alarms()
        else:
            print(f'Motor{self.mot_id} not on either switch')

    def home_with_limits(self):
        """
        Uses the limit switches to zero all motor positions.
        This function should only be used if the linear stages do not have
        home switches, and should be done carefully. Does one motor at a time
        in order to be careful.

        """
        # Basically, move motors until it hits the limit switch. This will
        # trigger an alarm
        self.move_axis_by_length(pos=-60, pos_is_inches=True, lin_stage=True)

        moving = True
        while moving:
            msg = self.ser.writeread('AL\r')
            # This is the error message for the limit switch near the motor
            if (msg == 'AL=0002'):
                print(
                    'Reached CCW limit switch. Moving 1 inch away from limit switch')
                pos = int(
                    1.0
                    * AXIS_THREADS_PER_INCH_STAGE
                    * self.s_p_rev
                    / 2.0)
                self.ser.write('DI%i\r' % (pos))  # DI = Distance/Position
                self.ser.write('FL\r')  # FL = Feed to Length
                self.ser.flushInput()

                # Wait for motor to get off limit switch and reset alarms
                sleep(3)
                print('Resetting alarms')
                self.reset_alarms()

            if not self.is_moving():
                # zero motor and encoder
                print(f'Zeroing {self.mot_id}')
                sleep(1)
                self.set_zero()
                self.set_encoder_value()
                # move on to next stage
                moving = False
        print('Stage zeroed using limit switch')

    def start_jogging(self):
        """
        Starts jogging control for specified motors.

        """
        self.ser.write('JE\r')  # JE = Jog Enable
        # WI = Wait for Input - Set into wait mode on empty input pin
        self.ser.write('WI4L\r')
        self.ser.flushInput()

    def stop_jogging(self):
        """
        Stop jogging control to all motors.

        """
        self.kill_all_commands()

    def seek_home_linear_stage(self):
        """
        Move the linear stage to its home position using the home
        limit switch.

        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving()
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        elif not self.is_lin:
            print("Motor isn't connected to a linear stage.")
        self.ser.write('VE2.0\r')  # VE = Velocity
        self.ser.write('AC2.0\r')  # AC = Acceleration Rate
        self.ser.write('DE2.0\r')  # DE = Deceleration
        self.ser.write('DI-1\r')  # DI = Distance/Position (sets direction)
        self.ser.write('SHX3L\r')  # SH = Seek Home
        self.ser.flushInput()
        print("Linear stage homing...")
        self.block_while_moving(verbose=True)

        print("Linear stage home found.")

    def set_zero(self):
        """
        Tell the motor to set the current position as the zero
        point.

        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving()
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        self.pos = 0
        self.real_pos = 0.0
        self.ser.write('SP0\r')  # SP = Set Position
        self.ser.flushInput()

    def get_position(self):
        """
        Get the position of the motor in counts, relative to the set
        zero point (or starting point).

        Returns:
            positions (list): The positions in counts of the specified motors.
        """
        positions = []
        if not self.ser:
            print("Specified motor is invalid - no position info.")
            positions.append(None)
        else:
            positions.append(self.pos)
        return positions

    def get_position_in_inches(self):
        """
        Get the position of the motor in inches, relative to the set
        zero point (or starting point).

        Returns:
            real_positions (list): The positions in inches of the specified
            motors.
        """
        real_positions = []
        if not self.ser:
            print("Specified motor is invalid - no position info.")
            real_positions.append(None)
        else:
            real_positions.append(self.real_pos)
        return real_positions

    def get_immediate_position(self, inches=True):
        """
        Get the position of the motor while it is currently in
        motion. An estimate based on the calculated trajectory of the movement,
        relative to the zero point.

        Parameters:
            inches (bool): Whether the returned position should be in units of
                inches or not.

        Returns:
            positions (list): The positions of each motor, in either inches or
                counts.

        """
        positions = []
        counts_to_inches = 100000  # empirically, 100,000 counts per inch
        # Check that the motor position output is in the right mode
        msg = self.ser.writeread('IF\r')
        if msg == 'IF=H':
            # Output is coming out in hexadecimal, switching to decimal
            print('Changing output to decimal')
            self.ser.writeread('IFD\r')

        i_pos = self.ser.writeread('IP\r')
        sleep(0.1)
        self.ser.flushInput()
        i_pos = int(i_pos.rstrip('\r')[3:])
        if inches:
            i_pos = i_pos / counts_to_inches
        positions.append(i_pos)

        return positions

    def move_axis_to_position(
            self,
            pos=0,
            pos_is_inches=False,
            lin_stage=True):
        """
        Move the axis to the given absolute position in counts or
        inches.

        Parameters:
            pos (float): The desired position in counts or in inches, positive
                indicates away from the motor. (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts. (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not. (default True)
        """
        # Set the threads per inch based on if the motor controls the FTS
        # linear stage
        if lin_stage:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
        else:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

        # Convert from inches if necessary
        if (pos_is_inches):
            # 2.0 is because threads go twice the distance for one
            # revolution
            unit_pos = int(pos * AXIS_THREADS_PER_INCH
                           * self.s_p_rev / 2.0)
        else:
            unit_pos = int(pos)
        # Set the new pos and real_pos parameters of the motor object
        self.pos = unit_pos
        self.real_pos = 2.0 * unit_pos / \
            (AXIS_THREADS_PER_INCH * self.s_p_rev)  # See 2.0 note above
        # Move the motor
        self.ser.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
        self.ser.write('FP\r')  # FL = Feed to Position
        self.ser.flushInput()

    def move_axis_by_length(
            self,
            pos=0,
            pos_is_inches=True,
            lin_stage=True):
        """
        Move the axis relative to the current position by the
        specified number of counts or inches.

        Parameters:
            pos (float): the desired number of counts or inches to move from
                current position, positive indicates away from the motor.
                (default 0)
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts. (default False)
            lin_stage (bool): True if the specified motor is for the linear
                stage, False if not. (default True)
        """
        # Set the threads per inch based on if the motor controls the FTS
        # linear stage
        if lin_stage:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_STAGE
        else:
            AXIS_THREADS_PER_INCH = AXIS_THREADS_PER_INCH_XYZ

        # Convert from inches if necessary
        if pos_is_inches:
            unit_pos = int(
                pos
                * AXIS_THREADS_PER_INCH
                * self.s_p_rev
                / 2.0)  # See 2.0 note above
        else:
            unit_pos = int(pos)

        # Set the new pos and real_pos parameters of the motor object
        self.pos += unit_pos
        self.real_pos += 2.0 * unit_pos / \
            (AXIS_THREADS_PER_INCH * self.s_p_rev)  # See 2.0 note above

        # Move the motor
        self.ser.write('DI%i\r' % (unit_pos))  # DI = Distance/Position
        self.ser.write('FL\r')  # FL = Feed to Length
        self.ser.flushInput()
        print(unit_pos)
        print("Final position: ", pos)

    def set_velocity(self, velocity=1.0):
        """
        Set velocity in revolutions/second.  Range is 0.25 - 50.
        Accepts floating point values.

        Parameters:
            velocity (float): Sets velocity of motor in revolutions per second
                within range [0.25,50]. (default 1.0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving()
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        self.ser.write('VE%1.3f\r' % (velocity))  # VE = Velocity
        self.ser.flushInput()

    def set_acceleration(self, accel=5):
        """
        Set acceleration of motors driving stages. (default 5)

        Parameters:
            accel (int): Sets acceleration in revolutions per second per second
                within range [1,3000]. (default 5)
        """
        self.ser.write('AC%i\r' % (accel))  # AC = Acceleration Rate
        self.ser.write('DE%i\r' % (accel))  # DE = Deceleration
        self.ser.flushInput()

    def kill_all_commands(self):
        """
        Stop all active commands on the device.
        """
        # SK = Stop & Kill - Stop/kill all commands, turn off waiting for
        # input
        self.ser.write('SK\r')
        self.ser.flushInput()

    def block_while_moving(self, update_period=.1, verbose=False):
        """
        Block until the specified axes have stop moving. Checks each
        axis every update_period seconds.

        Parameters:
            update_period (float): Time after which to check each motor in
                seconds. (default .1)
            verbose (bool): Prints output from motor requests if True.
                (default False)
        """
        self.ser.flushInput()
        msg = self.ser.writeread('RS\r')
        count = 0
        while (msg != 'RS=R'):
            count += 1
            self.ser.flushInput()
            # Get the status of the motor and print if verbose = True
            msg = self.ser.writeread('RS\r')  # RS = Request Status
            self.ser.flushInput()
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

    def run_positions(self, pos_data, pos_is_inches=False):
        """
        Runs a list of entries as positions. For
        motor=ALL, the first column must be the x-data, and the second column
        the y-data. Each position will be attained.

        Parameters:
            pos_data (list): Tab-delimited list of entries. First column
                is x-data, second column is y-data.
            pos_is_inches (bool): True if pos was specified in inches, False if
                in counts (default False)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving()
        if move_status:
            print('Motors are still moving. Try again later.')
            return
        self.move_axis_to_position(pos_data, pos_is_inches=pos_is_inches)

        print(f'Moving position to {pos_data}')

    def set_motor_enable(self, enable=True):
        """
        Set motor enable to true or false for given axis. Should
        disable motor when stopped for lower noise data acquisition.

        Parameters:
            enable (bool): Enables specified motor if True, disables specified
                motor if False.
        """
        if enable:
            self.ser.write('ME\r')  # ME = Motor Enable
        else:
            self.ser.write('MD\r')  # MD = Motor Disable
        self.ser.flushInput()

    def retrieve_encoder_info(self):
        """
        Retrieve all motor step counts to verify movement.
        """
        move_status = self.is_moving()
        e_positions = []

        # If the motors are moving, return NaNs to keep from querying the
        # motor controllers during motion.
        if move_status:
            e_positions.append(np.nan)
            return e_positions

        e_pos = self.ser.writeread('EP\r')  # EP = Encoder Position
        sleep(0.1)
        self.ser.flushInput()
        e_pos = int(e_pos.rstrip('\r')[3:])
        e_positions.append(e_pos)

        return e_positions

    def set_encoder_value(self, value=0):
        """
        Set the encoder values in order to keep track of absolute
        position.

        Parameters:
            value (float): Sets encoder value. (default 0)
        """
        # Check if either motor is moving, and if yes exit function with an
        # error message
        move_status = self.is_moving()
        if move_status:
            print('Motors are still moving. Try again later.')
            return

        e_positions = []
        # Set the motor position
        self.ser.write('EP%i\r' % (value))  # EP = Encoder Position
        sleep(0.1)
        self.ser.flushInput()
        # Read and return the new motor position
        e_pos = self.ser.writeread('EP\r')  # EP = Encoder Position
        sleep(0.1)
        self.ser.flushInput()
        e_pos = int(e_pos.rstrip('\r')[3:])
        print(e_pos)
        e_positions.append(e_pos)

        return e_positions

    def start_rotation(self, velocity=12.0, rot_accel=1.0):
        """
        Starts jogging specifically for the rotation of the output
        polarizer in the FTS.

        Parameters:
            velocity (float): The rotation velocity in revolutions per second (default 12.0)
            rot_accel (float): The acceleration in revolutions per second per
                second within range [1,3000].  (default 1.0)
        """
        # Set the jog parameters
        self.ser.write('JS%1.3f\r' % (velocity))  # JS = Jog Speed
        self.ser.write('JA%i\r' % (rot_accel))  # JA = Jog Acceleration
        self.ser.write('JL%i\r' % (rot_accel))  # JL = Jog Decel

        # Start rotation
        self.ser.write('CJ\r')  # CJ = Commence Jogging
        self.ser.flushInput()

    def stop_rotation(self):
        """
        Stops jogging for the rotation of the specified motor.
        """
        self.ser.write('SJ\r')  # SJ = Stop Jogging
        self.ser.flushInput()

    def reset_alarms(self):
        """
        Resets alarm codes present. Only advised if you have checked
        what the alarm is first!
        """
        self.ser.write('AR\r')
        self.ser.flushInput()

    def close_connection(self):
        """
        Close the connection to the serial controller for the
        specified motor.
        """
        self.ser.close()
        print("Connection to serial controller disconnected.")

    def reconnect_motor(self):
        """
        Reestablish connection with specified motor.
        """
        print(f"port: {self.port}")
        try:
            self.ser.sock.close()
            time.sleep(1)
            del self.ser
            self.ser = Serial_TCPServer((self.ip, self.port))
            print("Connection has been established.")
            self.sock_status = 1
        except ConnectionError:
            print("Connection could not be reestablished.")
            self.sock_status = 0
