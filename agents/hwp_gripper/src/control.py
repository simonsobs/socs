# Built-in python modules
import time as tm
import sys
import os

class Control:
    """
    The Control object is a class to package gripper controller operations

    Args:
    JXC (src.JXC): JXC object

    Attributes:
    log (src.Logging): logging object
    """
    def __init__(self, JXC):
        if JXC is None:
            raise Exception(
                'Control Error: Control() constructor requires a '
                'controller object')
        self._JXC = JXC

        # Timout and timestep
        self._tout = 25.0  # sec
        self._tstep = 0.1  # sec

        # Dictionary of pins to write for each step number
        # Binary input = step number + 1
        self.step_inputs = {
            "01": [self._JXC.IN0],
            "02": [self._JXC.IN1],
            "03": [self._JXC.IN0, self._JXC.IN1],
            "04": [self._JXC.IN2],
            "05": [self._JXC.IN0, self._JXC.IN2],
            "06": [self._JXC.IN1, self._JXC.IN2],
            "07": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN2],
            "08": [self._JXC.IN3],
            "09": [self._JXC.IN0, self._JXC.IN3],
            "10": [self._JXC.IN1, self._JXC.IN3],
            "11": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN3],
            "12": [self._JXC.IN2, self._JXC.IN3],
            "13": [self._JXC.IN0, self._JXC.IN2, self._JXC.IN3],
            "14": [self._JXC.IN1, self._JXC.IN2, self._JXC.IN3],
            "15": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN2, self._JXC.IN3],
            "16": [self._JXC.IN4],
            "17": [self._JXC.IN0, self._JXC.IN4],
            "18": [self._JXC.IN1, self._JXC.IN4],
            "19": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN4],
            "20": [self._JXC.IN2, self._JXC.IN4],
            "21": [self._JXC.IN0, self._JXC.IN2, self._JXC.IN4],
            "22": [self._JXC.IN1, self._JXC.IN2, self._JXC.IN4],
            "23": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN2, self._JXC.IN4],
            "24": [self._JXC.IN3, self._JXC.IN4],
            "25": [self._JXC.IN0, self._JXC.IN3, self._JXC.IN4],
            "26": [self._JXC.IN1, self._JXC.IN3, self._JXC.IN4],
            "27": [self._JXC.IN0, self._JXC.IN1, self._JXC.IN3, self._JXC.IN4],
            "28": [self._JXC.IN2, self._JXC.IN3, self._JXC.IN4],
            "29": [self._JXC.IN0, self._JXC.IN2, self._JXC.IN3, self._JXC.IN4],
            "30": [self._JXC.IN1, self._JXC.IN2, self._JXC.IN3, self._JXC.IN4]}

        # Dictionary of pins to write for each step number
        # Binary input = step number + 1
        self.step_outputs = {
            "01": [self._JXC.OUT0],
            "02": [self._JXC.OUT1],
            "03": [self._JXC.OUT0, self._JXC.OUT1],
            "04": [self._JXC.OUT2],
            "05": [self._JXC.OUT0, self._JXC.OUT2],
            "06": [self._JXC.OUT1, self._JXC.OUT2],
            "07": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT2],
            "08": [self._JXC.OUT3],
            "09": [self._JXC.OUT0, self._JXC.OUT3],
            "10": [self._JXC.OUT1, self._JXC.OUT3],
            "11": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT3],
            "12": [self._JXC.OUT2, self._JXC.OUT3],
            "13": [self._JXC.OUT0, self._JXC.OUT2, self._JXC.OUT3],
            "14": [self._JXC.OUT1, self._JXC.OUT2, self._JXC.OUT3],
            "15": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT2,
                   self._JXC.OUT3],
            "16": [self._JXC.OUT4],
            "17": [self._JXC.OUT0, self._JXC.OUT4],
            "18": [self._JXC.OUT1, self._JXC.OUT4],
            "19": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT4],
            "20": [self._JXC.OUT2, self._JXC.OUT4],
            "21": [self._JXC.OUT0, self._JXC.OUT2, self._JXC.OUT4],
            "22": [self._JXC.OUT1, self._JXC.OUT2, self._JXC.OUT4],
            "23": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT2,
                   self._JXC.OUT4],
            "24": [self._JXC.OUT3, self._JXC.OUT4],
            "25": [self._JXC.OUT0, self._JXC.OUT3, self._JXC.OUT4],
            "26": [self._JXC.OUT1, self._JXC.OUT3, self._JXC.OUT4],
            "27": [self._JXC.OUT0, self._JXC.OUT1, self._JXC.OUT3,
                   self._JXC.OUT4],
            "28": [self._JXC.OUT2, self._JXC.OUT3, self._JXC.OUT4],
            "29": [self._JXC.OUT0, self._JXC.OUT2, self._JXC.OUT3,
                   self._JXC.OUT4],
            "30": [self._JXC.OUT1, self._JXC.OUT2, self._JXC.OUT3,
                   self._JXC.OUT4]}

        # Dictionary of Alarm OUTputs
        # Output 0, 1, 2, 3
        self.alarm_group = {}
        self.alarm_group["B"] = '0100'
        self.alarm_group["C"] = '0010'
        self.alarm_group["D"] = '0001'
        self.alarm_group["E"] = '0000'

    # ***** Public Methods *****
    def ON(self):
        """ Turn the controller on """
        # Turn SVON on
        if not self._JXC.read(self._JXC.SVON):
            self._JXC.set_on(self._JXC.SVON)
        self._sleep()
        if not self._JXC.read(self._JXC.SVON):
            print("Failed to turn SVON on")
            return False
        else:
            print("SVON turned on in Control.ON()")

        # Turn off the brakes
        if (not self._JXC.read(self._JXC.BRAKE1) or
           not self._JXC.read(self._JXC.BRAKE2) or
           not self._JXC.read(self._JXC.BRAKE3)):
            self.BRAKE(False)
        self._sleep()
        if (not self._JXC.read(self._JXC.BRAKE1) or
           not self._JXC.read(self._JXC.BRAKE2) or
           not self._JXC.read(self._JXC.BRAKE3)):
            print("Failed to disengage brakes in Control.ON()")
            return False
        else:
            print("Disengaged brakes in Control.ON()")

        return True

    def OFF(self):
        """ Turn the controller off """
        # Turn on the brakes
        if (self._JXC.read(self._JXC.BRAKE1) or
           self._JXC.read(self._JXC.BRAKE2) or
           self._JXC.read(self._JXC.BRAKE3)):
            self.BRAKE(True)
        self._sleep()
        if (self._JXC.read(self._JXC.BRAKE1) or
           self._JXC.read(self._JXC.BRAKE2) or
           self._JXC.read(self._JXC.BRAKE3)):
            print("Failed to engage brakes in Control.OFF()")
            return False
        else:
            print("Brakes engaged in Control.OFF()")

        # Turn SVON off
        if self._JXC.read(self._JXC.SVON):
            self._JXC.set_off(self._JXC.SVON)
        self._sleep()
        if self._JXC.read(self._JXC.SVON):
            print("Failed turn SVON off in Control.OFF()")
            return False
        else:
            print("SVON turned off in Control.OFF()")

        return True

    def HOME(self):
        """ Home all actuators """
        # Make sure the motors are on
        if not self.ON():
            print("Control.HOME() aborted due to SVON not being ON")
            return False
        # Check SVRE
        if not self._is_powered():
            print("Control.HOME() aborted due to SVRE not being ON -- timeout")
            return False
        # Check for alarms
        if self._JXC.read(self._JXC.ALARM):
            print("Control.HOME() aborted due to an alarm being triggered")
            return False
        # Check for emergency stop
        if self._JXC.read(self._JXC.ESTOP):
            print("Control.HOME() aborted due to emergency stop being on")
            return False

        # Home the actuators
        self._JXC.set_on(self._JXC.SETUP)
        self._sleep()
        if not self._JXC.read(self._JXC.SETUP):
            print("Control.HOME() aborted due to failure to set SETUP to ON")
        if self._wait():
            print("'HOME' operation finished in Control.HOME()")
            # Engage the brake
            # self.BRAKE(state=True)
            self._JXC.set_off(self._JXC.SETUP)
            return True
        else:
            print("'HOME' operation failed in Control.HOME() due to timeout")
            # Engage the brake
            # self.BRAKE(state=True)
            self._JXC.set_off(self._JXC.SETUP)
            return False

    def STEP(self, step_num, axis_no=None):
        """
        Execute specified step for the controller

        Args:
        step_num (int): step number
        axis_no (int): axis number (default is None, which enables all axes)
        """
        # Make sure the motor is turned on
        if not self.ON():
            print("Control.STEP() aborted due to SVON not being ON")
            return False
        # Check for valid step number
        step_num = "%02d" % (int(step_num))
        if step_num not in self.step_inputs.keys():
            print(
                "Control.STEP() aborted due to unrecognized "
                "step number %02d not an " % (step_num))
            return False
        # Check that the motors aren't moving
        if self._is_moving():
            print("Control.STEP() aborted due to BUSY being on")
            return False
        # Check that the motors are ready to move
        if not self._is_ready():
            print("Control.STEP() aborted due to SETON not being on")
            return False

        # Set the inputs
        for addr in self.step_inputs[step_num]:
            self._JXC.set_on(addr)
        self._sleep()
        for addr in self.step_inputs[step_num]:
            if not self._JXC.read(addr):
                print(
                    "Control.STEP() aborted due to failure to set addr %d "
                    "to TRUE for step no %d" % (int(addr), step_num))
                return False

        # Drive the motor
        self._JXC.set_on(self._JXC.DRIVE)
        self._sleep()
        if not self._JXC.read(self._JXC.DRIVE):
            print("Control.STEP() aborted due to failure to set DRIVE to ON")
            return False
        # Wait for the motors to stop moving
        if self._wait():
            print(
                "Control.STEP() operation finished for step %d"
                % (int(step_num)))
            timeout = False
        # Otherwise the operation times out
        else:
            print(
                "STEP operation for step no %02d in Control.STEP() failed "
                "due to timout" % (int(step_num)))
            timeout = True

        # Reset inputs
        for addr in self.step_inputs[step_num]:
            self._JXC.set_off(addr)
        for addr in self.step_inputs[step_num]:
            if self._JXC.read(addr):
                print(
                    "Failed to reset addr %d after STEP command in "
                    "Control.STEP() for step no %02d"
                    % (int(addr), int(step_num)))
        # Turn off the drive
        self._JXC.set_off(self._JXC.DRIVE)
        if self._JXC.read(self._JXC.DRIVE):
            print(
                "Failed to turn off DRIVE after STEP command in "
                "Control.STEP() for step no %02d"
                % (int(step_num)))

        return not timeout

    def HOLD(self, state=True):
        """
        Turn on and off a HOLD of the motors

        Args:
        state (bool): True to turn HOLD on, False to turn it off
        """
        # Turn HOLD on
        if state is True:
            if self._is_moving():
                self._JXC.set_on(self._JXC.HOLD)
                self._sleep()
                if not self._JXC.read(self._JXC.HOLD):
                    print(
                        "Failed to apply HOLD to moving grippers in "
                        "Control.HOLD()")
                    return False
                else:
                    print("Applied HOLD to moving grippers")
                return True
            else:
                print("Cannot apply HOLD when grippers are not moving")
                self._JXC.set_off(self._JXC.HOLD)
                self._sleep()
                if self._JXC.read(self._JXC.HOLD):
                    print(
                        "Failed to turn HOLD off after failed HOLD "
                        "operation in Control.HOLD()")
                return False
        # Turn HOLD off
        elif state is False:
            self._JXC.set_off(self._JXC.HOLD)
            self._sleep()
            if self._JXC.read(self._JXC.HOLD):
                print(
                    "Failed to turn HOLD off after failed HOLD "
                    "operation in Control.HOLD()")
                return False
            else:
                print("HOLD set to off")
                return True
        # Cannot understand HOLD argument
        else:
            print(
                "Could not understand argument %s to Control.HOLD()"
                % (str(state)))
            return False

    def BRAKE(self, state=True, axis=None):
        """
        Turn the motor brakes on or off

        Args:
        state (bool): brake states. True for on, False for off
        axis (1-3): axis on which to apply the brake (default is all)
        """
        # Check the inputs
        if axis is None:
            axes = range(3)
        else:
            if type(axis) is int and int(axis) > 0 and int(axis) < 4:
                axes = [axis - 1]
            else:
                print(
                    "Could not understand axis %s passed to "
                    "Control.BRAKE()" % (str(axis)))
                return False

        # Set the brakes
        brakes = [self._JXC.BRAKE1, self._JXC.BRAKE2, self._JXC.BRAKE3]
        for ax in axes:
            if state:  # yes, it's inverted logic
                self._JXC.set_off(brakes[ax])
                print(
                    "Turned on BRAKE for axis %d in Control.BRAKE()"
                    % (int(ax + 1)))
            else:
                self._JXC.set_on(brakes[ax])
                print(
                    "Turned off BRAKE for axis %d in Control.BRAKE()"
                    % (int(ax + 1)))
        self._sleep()

        # Check the execution
        ret = True
        for ax in axes:
            read_out = self._JXC.read(brakes[ax])
            if state:  # yes, it's inverted logic
                if read_out:
                    print(
                        "Failed to turn on BRAKE for axis %d in "
                        "Control.BRAKE()" % (int(ax + 1)))
                    ret *= False
                else:
                    print(
                        "Successfully turned on BRAKE for axis %d "
                        "in Control.BRAKE()" % (int(ax + 1)))
                    ret *= True
            else:
                if not read_out:
                    print(
                        "Failed to turn off BRAKE for axis %d in "
                        "Control.BRAKE()" % (int(ax + 1)))
                    ret *= False
                else:
                    print(
                        "Successfully turned off BRAKE for axis %d "
                        "in Control.BRAKE()" % (int(ax + 1)))
                    ret *= True

        return ret

    def EMG(self, state=True, axis=None):
        if axis is None:
            axes = range(3)
        else:
            if type(axis) is int and int(axis) > 0 and int(axis) < 4:
                axes = [axis - 1]
            else:
                print(
                    "Could not understand axis %s passed to "
                    "Control.EMG()" % (str(axis)))
                return False

        emg_stop = [self._JXC.EMG1, self._JXC.EMG2, self._JXC.EMG3]
        for ax in axes:
            if state:
                self._JXC.set_on(emg_stop[ax])
                print(
                    "Turned on EMG for axis %d in Control.EMG()"
                    % (int(ax + 1)))
            else:
                self._JXC.set_off(emg_stop[ax])
                print(
                    "Turned off EMG for axis %d in Control.EMG()"
                    % (int(ax + 1)))
        self._sleep()

        ret = True
        for ax in axes:
            read_out = self._JXC.read(emg_stop[ax])
            if state:
                if not read_out:
                    print(
                        "Failed to turn on EMG for axis %d in "
                        "Control.EMG()" % (int(ax + 1)))
                    ret *= False
                else:
                    print(
                        "Successfully turned on EMG for axis %d "
                        "in Control.EMG()" % (int(ax + 1)))
                    ret *= True
            else:
                if read_out:
                    print(
                        "Failed to turn off EMG for axis %d in "
                        "Control.EMG()" % (int(ax + 1)))
                    ret *= False
                else:
                    print(
                        "Successfully turned off EMG for axis %d "
                        "in Control.EMG()" % (int(ax + 1)))
                    ret *= True

        return ret

    def RESET(self):
        """ Reset the alarm """
        if self._is_alarm():
            # Toggle the RESET pin on
            self._JXC.set_on(self._JXC.RESET)
            self._sleep()
            if not self._JXC.read(self._JXC.RESET):
                print("Failed to turn on RESET pin in Control.RESET()")
                return False
            # Toggle the RESET pin off
            self._JXC.set_off(self._JXC.RESET)
            self._sleep()
            if self._JXC.read(self._JXC.RESET):
                print(
                    "Failed to turn off RESET pin in Control.RESET() "
                    "after RESET was performed")
                return False
            # Check whether the ALARM was reset
            if self._is_alarm():
                print(
                    "Failed to RESET ALARM state. ALARM may be immutable")
                return False
        else:
            print(
                "RESET operation ignored in Control.RESET(). "
                "No ALARM detected")
        return True

    def OUTPUT(self):
        """ Read the OUTPUT pins """
        out0 = int(not self._JXC.read(self._JXC.OUT0))
        out1 = int(not self._JXC.read(self._JXC.OUT1))
        out2 = int(not self._JXC.read(self._JXC.OUT2))
        out3 = int(not self._JXC.read(self._JXC.OUT3))
        return str(out0), str(out1), str(out2), str(out3)

    def INP(self):
        """ Read the INP pins """
        self.ON()
        self._sleep(1.)
        out = int(not self._JXC.read(self._JXC.INP))
        return bool(out)

    def ACT(self, axis):
        if axis == 1:
            out = int(self._JXC.read(self._JXC.ACT1))
        if axis == 2:
            out = int(self._JXC.read(self._JXC.ACT2))
        if axis == 3:
            out = int(self._JXC.read(self._JXC.ACT3))
        print('Actuator {} is in state {}'.format(axis, out))
        return bool(out)

    def STATUS(self):
        """ Print the control status """
        print("CONTROL STATUS:")
        print("IN0 = %d" % (self._JXC.read(self._JXC.IN0)))
        print("IN1 = %d" % (self._JXC.read(self._JXC.IN1)))
        print("IN2 = %d" % (self._JXC.read(self._JXC.IN2)))
        print("IN3 = %d" % (self._JXC.read(self._JXC.IN3)))
        print("IN4 = %d" % (self._JXC.read(self._JXC.IN4)))
        print("\n")
        print("SETUP = %d" % (self._JXC.read(self._JXC.SETUP)))
        print("HOLD  = %d" % (self._JXC.read(self._JXC.HOLD)))
        print("DRIVE = %d" % (self._JXC.read(self._JXC.DRIVE)))
        print("RESET = %d" % (self._JXC.read(self._JXC.RESET)))
        print("SVON  = %d" % (self._JXC.read(self._JXC.SVON)))
        print("\n")
        print("OUT0 = %d" % (not self._JXC.read(self._JXC.OUT0)))
        print("OUT1 = %d" % (not self._JXC.read(self._JXC.OUT1)))
        print("OUT2 = %d" % (not self._JXC.read(self._JXC.OUT2)))
        print("OUT3 = %d" % (not self._JXC.read(self._JXC.OUT3)))
        print("OUT4 = %d" % (not self._JXC.read(self._JXC.OUT4)))
        print("\n")
        print("BUSY  = %d" % (not self._JXC.read(self._JXC.BUSY)))
        print("AREA  = %d" % (not self._JXC.read(self._JXC.AREA)))
        print("SETON = %d" % (not self._JXC.read(self._JXC.SETON)))
        print("INP   = %d" % (not self._JXC.read(self._JXC.INP)))
        print("SVRE  = %d" % (not self._JXC.read(self._JXC.SVRE)))
        print("ESTOP = %d" % (self._JXC.read(self._JXC.ESTOP)))
        print("ALARM = %d" % (self._JXC.read(self._JXC.ALARM)))
        print("\n")
        print("BRAKE1 = %d" % (not self._JXC.read(self._JXC.BRAKE1)))
        print("BRAKE2 = %d" % (not self._JXC.read(self._JXC.BRAKE2)))
        print("BRAKE3 = %d" % (not self._JXC.read(self._JXC.BRAKE3)))
        print("\n")
        print("EMG1 = %d" % (self._JXC.read(self._JXC.EMG1)))
        print("EMG2 = %d" % (self._JXC.read(self._JXC.EMG2)))
        print("EMG3 = %d" % (self._JXC.read(self._JXC.EMG3)))
        print("\n")
        return True

    def ALARM(self):
        """ Print the alarm status """
        print("ALARM = %d" % (self._JXC.read(self._JXC.ALARM)))
        return self._is_alarm()

    def ALARM_GROUP(self):
        """ Identify the alarm group """
        # ID the alarm group
        if self._is_alarm():
            outs = self.OUTPUT()
            output = ''.join(outs)
            for k in self.alarm_group.keys():
                if output == self.alarm_group[k]:
                    print("ALARM GROUP '%s' detected" % (k))
                    return k
                else:
                    continue
        # Otherwise no alarm
        else:
            print("Ignored Control.ALARM_GROUP(). No ALARM detected")
            return None

        # Alarm group not understood
        print("ALARM_GROUP id failed -- unknown output:")
        for i in range(4):
            print("OUT%d = %d" % (i, int(outs[i])))
        return None

    # ***** Private Methods ******
    def _sleep(self, time=None):
        """ Sleep for a specified amount of time """
        if time is None:
            tm.sleep(self._tstep)
        else:
            tm.sleep(time)
        return

    def _is_moving(self):
        """ Return whether the motors are moving """
        if not self._JXC.read(self._JXC.BUSY):
            return True
        else:
            return False

    def _is_ready(self):
        """ Returns whether the motors are ready to move """
        if not self._JXC.read(self._JXC.SETON):
            return True
        else:
            return False

    def _is_powered(self):
        """ Returns whether the motors are powered """
        t = 0.  # stopwatch
        while t < self._tout:
            if self._JXC.read(self._JXC.SVRE):
                self._sleep()
                t += self._tstep
                continue
            else:
                return True
        return False

    def _is_alarm(self):
        """ Returns whether an alarm is triggered """
        if self._JXC.read(self._JXC.ALARM):
            return True
        else:
            return False

    def _wait(self, stepNum=None, timeout=None):
        """ Function to wait for step_num to finish """
        if timeout is None:
            timeout = self._tout
        t = 0.  # stopwatch
        while t < timeout:
            if self._is_moving():
                self._sleep()
                t += self._tstep
                continue
            else:
                return True
        return False

