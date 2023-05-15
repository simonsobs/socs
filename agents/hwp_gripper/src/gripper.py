# Built-in python modules
import numpy as np

class Gripper:
    """
    The Gripper object is used to control the gripper motors

    Args:
    control (src.Control): Control object
    """
    def __init__(self, control):
        self.CTL = control

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

        # Execute steps
        steps = self._select_steps(mode, dist, axis_no)
        if steps is None:
            print(
                "MOVE aborted in Gripper.MOVE() due to no selected steps")
            return False
        for st in steps:
            if self.CTL.STEP(st, axis_no):
                continue
            else:
                print(
                    "MOVE aborted in Gripper.MOVE() due to "
                    "CTL.STEP() returning False")
                # self.INP()
                return False
        print(
            "MOVE in Gripper.MOVE() completed successfully")

        return self.INP()

    def HOME(self):
        """ Home all motors """
        # Home all motors
        if self.CTL.HOME():
            print(
                "HOME operation in Gripper.HOME() completed")
            return True
        else:
            print(
                "HOME operation failed in Gripper.HOME() due to CTL.HOME() returning False")
            print(
                "Actuators may be at unknown positions due to failed home operation")
            return False

    def ALARM(self):
        """ Return the ALARM state """
        return self.CTL.ALARM()

    def RESET(self):
        """ Reset the ALARM """
        # Obtain the alarm group
        group = self.CTL.ALARM_GROUP()
        if group is None:
            print(
                "RESET aborted in Gripper.RESET() due to no detected alarm")
            return False
        elif group == "B" or group == "C":
            print(
                "Clearing Alarm group '%s' via a RESET." % (group))
            return self.CTL.RESET()
        elif group == "D":
            print(
                "Clearing Alarm group '%s' via a RESET" % (group))
            return self.CTL.RESET()
        elif group == "E":
            print(
                "RESET failed in Gripper.RESET() due to alarm group '%s' "
                "detected. Power cycle of controller and motors required"
                % (group))
            return False
        else:
            print(
                "RESET aborted in Gripper.RESET() due to unknown alarm group")
            return False

        if not self.ALARM():
            print("Alarm successfully reset")
            return True
        else:
            print(
                "RESET aborted in Gripper.RESET() due to unknown error")
            return False

    def INP(self):
        """ Return control INP """
        outs = self.CTL.INP()
        # for i in range(3):
        #    print("INP%d = %d" % (i+1, outs[i]))
        return outs

    def ACT(self, axis):
        outs = self.CTL.ACT(axis)
        return outs

    def STATUS(self):
        """ Return control status """
        return self.CTL.STATUS()

    # ***** Helper Methods *****
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
                print(
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
