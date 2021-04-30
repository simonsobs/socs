# Built-in python modules
import sys as sy


class Command:
    def __init__(self, GPR=None):
        """
        The Command object handles user-input commands from the
        command-line program

        Args:
        GPR (src.Gripper): Gripper object
        """
        if GPR is None:
            raise Exception(
                "Command error: No gripper object passed "
                "to Command() constructor")
        else:
            self.GPR = GPR
        self.log = self.GPR.log

    def CMD(self, user_input):
        args = user_input.split(' ')
        cmd = args[0].upper()
        if cmd == 'HELP':
            return self._help()
        elif cmd == 'ON':
            return self.GPR.ON()
        elif cmd == 'OFF':
            return self.GPR.OFF()
        elif cmd == 'BRAKE':
            return self._brake(args)
        elif cmd == 'MOVE':
            return self._move(args)
        elif cmd == 'HOME':
            return self.GPR.HOME()
        elif cmd == 'INP':
            return self.GPR.INP()
        elif cmd == 'ALARM':
            return self.GPR.ALARM()
        elif cmd == 'RESET':
            return self.GPR.RESET()
        elif cmd == 'POSITION':
            return self.GPR.POSITION()
        elif cmd == 'SETPOS':
            return self._set_pos(args)
        elif cmd == 'STATUS':
            return self.GPR.STATUS()
        elif cmd == 'EXIT':
            self.GPR.OFF()
            sy.exit(0)
        else:
            self.log.err(
                "Cannot understand command '%s'. "
                "Type 'HELP' for a list of commands.")
            return False

    # ***** Helper Functions *****
    def _help(self):
        print("\n*** Gripper Control: Command Menu ***")
        print("HELP = help menu (you're here right now)")
        print("ON = turn grippers (SVON) on")
        print("OFF = turn grippers (SVON) off")
        print("BRAKE ON  [axis number (1-3)] = Engage brake on given axis. "
              "If axis not provided, engage brake on all axes.")
        print("BRAKE OFF [axis number (1-3)] = Release brake on given axis. "
              "If axis not provided, release brake on all axes.")
        print("MOVE [mode 'PUSH' or 'POS'] [axis number (1-3)] [distance (mm)]"
              " = move axis a given distance. Minimum step size = 0.1 mm")
        print("HOME = home all axes, resetting their positions to 0.0 mm")
        print("INP = in position (positioning operation) or pushing (pushing "
              "operation) flag")
        print("ALARM = display alarm state")
        print("RESET = reset alarm")
        print("POSITION = display actuator positions")
        print("SETPOS [axis number (1-3)] [distance (mm)] = manually set motor"
              " position without moving")
        print("STATUS = display status of all JXC controller bits")
        print("EXIT = exit this program\n")
        return True

    def _brake(self, args):
        ON = None
        if not (len(args) == 2 or len(args) == 3):
            self.log.err(
                "Cannot understand 'BRAKE' arguments: %s"
                % (' '.join(args[1:])))
            self.log.err(
                "Usage: BRAKE ON/OFF [axis number (1-3)]")
            return False
        if args[1].upper() == 'ON':
            ON = True
        elif args[1].upper() == 'OFF':
            ON = False
        else:
            self.log.err(
                "Cannot understand 'BRAKE' argument: %s"
                % (args[1]))
            self.log.err(
                "Usage: BRAKE ON/OFF [axis number (1-3)]\n")
            return False
        if len(args) == 3:
            try:
                axis = int(args[2])
            except ValueError:
                self.log.err(
                    "Cannot understand 'BRAKE' argument: %s"
                    % (args[2]))
                self.log.err(
                    "Usage: BRAKE ON/OFF [axis number (1-3)]\n")
                return False
            if axis < 1 or axis > 3:
                self.log.err(
                    "Cannot understand 'BRAKE' argument: %s"
                    % (args[2]))
                self.log.err(
                    "Usage: BRAKE ON/OFF [axis number (1-3)]\n")
                return False
            else:
                self.GPR.CTL.BRAKE(state=ON, axis=axis)
        else:
            for i in range(3):
                self.GPR.CTL.BRAKE(state=ON, axis=i+1)
        return

    def _move(self, args):
        if not len(args) == 4:
                self.log.err(
                    "Cannot understand 'MOVE' argument: %s"
                    % (' '.join(args[1:])))
                return False
        else:
            mode = str(args[1]).upper()
            if not (mode == 'PUSH' or mode == 'POS'):
                self.log.err(
                    "Cannot understand move mode '%s'. "
                    "Must be either 'PUSH' or 'POS'"
                    % (mode))
                return False
            try:
                axis = int(args[2])
            except ValueError:
                self.log.err(
                    "Cannot understand axis number = '%s'. "
                    "Must be an integer (1-3)." % (str(axis)))
                return False
            if axis == 1 or axis == 2 or axis == 3:
                try:
                    dist = float(args[3])
                    result = self.GPR.MOVE(mode, dist, axis)
                    return result
                except ValueError:
                    self.log.err(
                        "Cannot understand relative move distance '%s'. "
                        "Must be a float." % (str(dist)))
                    return False
            else:
                self.log.err(
                    "Cannot understand axis number '%d'. "
                    "Must be an integer (1-3)." % (axis))
                return False

    def _set_pos(self, args):
        if not len(args) == 3:
                self.log.err(
                    "Cannot understand 'MOVE' argument: %s"
                    % (' '.join(args[1:])))
                return False
        try:
            axis = int(args[1])
        except ValueError:
            self.log.err(
                "Cannot understand axis number = '%s'. "
                "Must be an integer (1-3)." % (str(axis)))
            return False
        if axis == 1 or axis == 2 or axis == 3:
            try:
                pos = float(args[2])
                result = self.GPR.SETPOS(axis, pos)
                return result
            except ValueError:
                self.log.err(
                    "Cannot understand new position '%s'. "
                    "Must be a float." % (str(pos)))
                return False
        else:
            self.log.err(
                "Cannot understand axis number '%d'. "
                "Must be an integer (1-3)." % (axis))
            return False
