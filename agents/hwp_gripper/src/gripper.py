# Built-in python modules
import datetime as dt
import numpy as np
import os

# CHWP modules
import motor as mt  # noqa: E402

class Gripper:
    """
    The Gripper object is used to control the gripper motors

    Args:
    control (src.Control): Control object
    """
    def __init__(self, control):
        self.CTL = control

        # Instantiate motor objects
        self.motors = {}
        self.motors["1"] = mt.Motor("Axis 1")
        self.motors["2"] = mt.Motor("Axis 2")
        self.motors["3"] = mt.Motor("Axis 3")
        self.num_motors = len(self.motors.keys())

        # Logging object
        self.log = self.CTL.log

        # Position file
        self.this_dir = os.path.dirname(__file__)
        self.pos_file = os.path.join(
            self.this_dir, "chwp_gripper_pos.txt")
        self.posf = open(self.pos_file, 'w+')

        # Read initial positions
        self._read_pos()

        # Minimum and maximum allowed positions
        self.minPos = -2.0
        self.maxPos = +20.0

        # Step dict of pushing operations
        self.steps_push = {}
        self.steps_push["01"] = (+0.1, +0.0, +0.0)
        self.steps_push["02"] = (+0.0, +0.1, +0.0)
        self.steps_push["03"] = (+0.0, +0.0, +0.1)
        self.steps_push["04"] = (+0.5, +0.0, +0.0)
        self.steps_push["05"] = (+0.0, +0.5, +0.0)
        self.steps_push["06"] = (+0.0, +0.0, +0.5)
        self.steps_push["07"] = (+1.0, +0.0, +0.0)
        self.steps_push["08"] = (+0.0, +1.0, +0.0)
        self.steps_push["09"] = (+0.0, +0.0, +1.0)

        # Step dict of all-motor operations
        self.steps_pos = {}
        self.steps_pos["10"] = (+0.1, +0.0, +0.0)
        self.steps_pos["11"] = (+0.0, +0.1, +0.0)
        self.steps_pos["12"] = (+0.0, +0.0, +0.1)
        self.steps_pos["13"] = (-0.1, +0.0, +0.0)
        self.steps_pos["14"] = (+0.0, -0.1, +0.0)
        self.steps_pos["15"] = (+0.0, +0.0, -0.1)
        self.steps_pos["16"] = (+0.5, +0.0, +0.0)
        self.steps_pos["17"] = (+0.0, +0.5, +0.0)
        self.steps_pos["18"] = (+0.0, +0.0, +0.5)
        self.steps_pos["19"] = (-0.5, +0.0, +0.0)
        self.steps_pos["20"] = (+0.0, -0.5, +0.0)
        self.steps_pos["21"] = (+0.0, +0.0, -0.5)
        self.steps_pos["22"] = (+1.0, +0.0, +0.0)
        self.steps_pos["23"] = (+0.0, +1.0, +0.0)
        self.steps_pos["24"] = (+0.0, +0.0, +1.0)
        self.steps_pos["25"] = (-1.0, +0.0, +0.0)
        self.steps_pos["26"] = (+0.0, -1.0, +0.0)
        self.steps_pos["27"] = (+0.0, +0.0, -1.0)
        self.steps_pos["28"] = (+5.0, +0.0, +0.0)
        self.steps_pos["29"] = (+0.0, +5.0, +0.0)
        self.steps_pos["30"] = (+0.0, +0.0, +5.0)

    def __del__(self):
        self.posf.close()
        return

    # ***** Public Methods *****
    def ON(self):
        """ Turn the controller on """
        return self.CTL.ON()

    def OFF(self):
        """ Turn the controller off """
        return self.CTL.OFF()

    def MOVE(self, mode, dist, axis_no):
        """
        Move a specified motor a specified distance

        Args:
        mode (str): 'POS' for positioning mode, 'PUSH' for pushing mode
        dist (float): distance to move the motor [mm]
        axis_no (int): axis to move (1-3)
        """
        motor = self.motors[str(axis_no)]

        # Execute steps
        steps = self._select_steps(mode, dist, axis_no)
        if steps is None:
            self.log.err(
                "MOVE aborted in Gripper.MOVE() due to no selected steps")
            return False
        for st in steps:
            if self.CTL.STEP(st, axis_no):
                if mode == 'POS':
                    motor.pos += self.steps_pos[st][axis_no-1]
                elif mode == 'PUSH':
                    motor.pos += self.steps_push[st][axis_no-1]
                continue
            else:
                self.log.err(
                    "MOVE aborted in Gripper.MOVE() due to "
                    "CTL.STEP() returning False")
                self.motors[str(axis_no)].pos = motor.pos
                if abs(dist) - abs(dist)//1 == 0:
                    self.motors[str(axis_no)].max_pos_err += 1.0
                else:
                    self.motors[str(axis_no)].max_pos_err += 0.1
                self._write_pos()
                # self.INP()
                return False
        self.log.log(
            "MOVE in Gripper.MOVE() completed successfully")

        # Write new position and return whether in position
        self.motors[str(axis_no)].pos = motor.pos
        self._write_pos()
        return self.INP()

    def HOME(self):
        """ Home all motors """
        # Home all motors
        if self.CTL.HOME():
            self.log.log(
                "HOME operation in Gripper.HOME() completed")
            # Store homed positions
            for k in self.motors.keys():
                self.motors[k].pos = self.motors[k].home_pos
                self.motors[k].max_pos_err = 0.
            self._write_pos()
            return True
        else:
            self.log.err(
                "HOME operation failed in Gripper.HOME() due to "
                "CTL.HOME() returning False")
            self.log.err(
                "Actuators may be at unknown positions due to failed "
                "home operation")
            return False

    def ALARM(self):
        """ Return the ALARM state """
        return self.CTL.ALARM()

    def RESET(self):
        """ Reset the ALARM """
        # Obtain the alarm group
        group = self.CTL.ALARM_GROUP()
        if group is None:
            self.log.err(
                "RESET aborted in Gripper.RESET() due to no detected alarm")
            return False
        elif group == "B" or group == "C":
            self.log.log(
                "Clearing Alarm group '%s' via a RESET." % (group))
            return self.CTL.RESET()
        elif group == "D":
            self.log.log(
                "Clearing Alarm group '%s' via a RESET" % (group))
            return self.CTL.RESET()
        elif group == "E":
            self.log.err(
                "RESET failed in Gripper.RESET() due to alarm group '%s' "
                "detected. Power cycle of controller and motors required"
                % (group))
            return False
        else:
            self.log.err(
                "RESET aborted in Gripper.RESET() due to unknown alarm group")
            return False
        if not self.ALARM():
            self.log.log("Alarm successfully reset")
            return True
        else:
            self.log.err(
                "RESET aborted in Gripper.RESET() due to unknown error")
            return False

    def POSITION(self):
        """ Print the gripper position """
        for k in self.motors.keys():
            self.log.out("Axis %s = %.02f mm" % (k, self.motors[k].pos))
        return True

    def SETPOS(self, axis_no, value):
        """ Set a user-defined position for a specific motor """
        self.log.out(
            "Axis %d old position = %.02f" % (axis_no, self.motors[str(axis_no)].pos))
        self.motors[str(axis_no)].pos = float(value)
        self.motors[str(axis_no)].max_pos_err = 0.
        self._write_pos()
        self.log.out(
            "Axis %d new position set manually = %.02f"
            % (axis_no, value))
        self.log.log(
            "Axis %d maximum position error zerod" % (axis_no))
        return True

    def INP(self):
        """ Return control INP """
        outs = self.CTL.INP()
        # for i in range(3):
        #    self.log.out("INP%d = %d" % (i+1, outs[i]))
        return outs

    def STATUS(self):
        """ Return control status """
        return self.CTL.STATUS()

    # ***** Helper Methods *****
    def _read_pos(self):
        """ Read motor positions from position file """
        lines = self.posf.readlines()
        if len(lines) == 0:
            self.motors["1"].pos = 0.
            self.motors["2"].pos = 0.
            self.motors["3"].pos = 0.
        else:
            lastWrite = lines[-1]
            date, time = lastWrite.split('[')[1].split(']')[0].split()
            pos1, pos2, pos3 = lastWrite.split()[2:]
            self.motors["1"].pos = float(pos1)
            self.motors["2"].pos = float(pos2)
            self.motors["3"].pos = float(pos3)
        return True

    def _write_pos(self, init=False):
        """ Write motor positions to position file """
        now = dt.datetime.now()
        date = "%04d-%02d-%02d" % (now.year, now.month, now.day)
        time = "%02d:%02d:%02d" % (now.hour, now.minute, now.second)
        wrmsg = (
            "[%s %s] %s %-20.2f %-20.2f %-20.2f\n"
            % (date, time, ' '*3,
               self.motors["1"].pos,
               self.motors["2"].pos,
               self.motors["3"].pos))
        self.posf.truncate(0)
        self.posf.write(wrmsg)
        return True

    def _select_steps(self, mode, dist, axis_no):
        """ Select the steps to move a specified motor """
        d = dist
        steps_to_do = []
        while abs(d) >= 0.1:  # mm
            # Check input mode
            if mode == 'PUSH':
                steps_to_check = self.steps_push
            elif mode == 'POS':
                steps_to_check = self.steps_pos
            else:
                self.log.log(
                    "Did not understand mode '%s' in "
                    "GRIPPER()._select_steps()" % (mode))
                return None
            # Loop over steps to construct move from largest to smallest
            for k in list(steps_to_check.keys())[::-1]:
                move_step = float(steps_to_check[k][axis_no-1])
                if np.round(move_step, decimals=1) == 0.0:
                    continue
                try:
                    div = np.round(float(d)/move_step, decimals=1)
                except ZeroDivisionError:
                    continue
                if div >= 1.0:
                    steps_to_do.append(k)
                    d -= move_step
                    break
                else:
                    continue
        return steps_to_do
