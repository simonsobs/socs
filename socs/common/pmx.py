import sys
import time

import serial

from socs.common import moxa_serial as mx


class PMX:
    """The PMX object is for communicating with the Kikusui PMX power supplies.

    Args:
        rtu_port (str): Serial RTU port
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
        timeout (int): Connection timeout
    """

    def __init__(self, rtu_port=None, tcp_ip=None, tcp_port=None, timeout=None):
        # Connect to device
        self.using_tcp = None
        self._rtu_port = None
        self.ser = None
        msg = self.__conn(rtu_port, tcp_ip, tcp_port, timeout)
        print(msg)
        self._remote_Mode()

        # Timing variables
        self._tstep = 0.1  # sec

    def __del__(self):
        if not self.using_tcp:
            print(
                "Disconnecting from RTU port %s"
                % (self._rtu_port))
            if self.ser:
                self.ser.close()
        else:
            print(
                "Disconnecting from TCP IP %s at port %d"
                % (self._tcp_ip, self._tcp_port))
        return

    def check_connect(self):
        """Check the connection."""
        try:
            if not self.using_tcp:
                self.ser.inWaiting()
            else:
                self.clean_serial()
                self.wait()
                self.ser.write("OUTP?\n\r")
                self.wait()
                val = (self.ser.readline().strip())
                val = int(val)
        except Exception as e:
            msg = 'Could not connect to the PMX serial! | Error: "{}"'.format(e)
            return msg, False
        return 'Successfully connect to the PMX serial.', True

    def check_voltage(self):
        """Check the voltage."""
        self.clean_serial()
        self.ser.write("MEAS:VOLT?\n\r")
        self.wait()
        try:
            val = float(self.ser.readline())
            msg = "Measured voltage = %.3f V" % (val)
            # print(msg)
        except ValueError:
            val = -999.
            msg = 'WARNING! Could not get correct voltage value! | Response = "%s"' % (val)
            print(msg)
        return msg, val

    def check_current(self):
        """Check the current."""
        self.clean_serial()
        self.ser.write("MEAS:CURR?\n\r")
        self.wait()
        try:
            val = self.ser.readline()
            curr = float(val)
            msg = "Measured current = %.3f A" % (curr)
            # print(msg)
        except ValueError:
            print(f"Could not convert '{val}' to float")
            curr = -999.
            msg = 'WARNING! Could not get correct current value! | Response = "%s"' % (val)
            print(msg)
        return msg, curr

    def check_voltage_current(self):
        """Check both the voltage and current."""
        self.clean_serial()
        voltage = self.check_voltage()[1]
        current = self.check_current()[1]
        # msg = (
        #     "Measured voltage = %.3f V\n"
        #     "Measured current = %.3f A\n"
        #     % (voltage, current))
        # print(msg)
        return voltage, current

    def check_voltage_setting(self):
        """ Check the voltage setting """
        self.clean_serial()
        for i in range(10):
            self.ser.write("VOLT?\n\r")
            self.wait()
            val = (self.ser.readline().strip())
            if len(val) > 0:
                break
        try:
            val = float(val)
            msg = "Voltage setting = %.3f V" % (val)
            # print(msg)
        except ValueError:
            val = -999.
            msg = 'WARNING! Could not get correct voltage-setting value! | Response = "%s"' % (val)
            print(msg)
        return msg, val

    def check_current_setting(self):
        """ Check the current setting """
        self.clean_serial()
        for i in range(10):
            self.ser.write("CURR?\n\r")
            self.wait()
            val = (self.ser.readline().strip())
            if len(val) > 0:
                break
        try:
            val = float(val)
            msg = "Current setting = %.3f A" % (val)
            # print(msg)
        except ValueError:
            val = -999.
            msg = 'WARNING! Could not get correct current-setting value! | Response = "%s"' % (val)
            print(msg)
        return msg, val

    def check_voltage_current_setting(self):
        """ Check both the voltage and current setting """
        self.clean_serial()
        voltage = self.check_voltage_setting()[1]
        current = self.check_current_setting()[1]
        msg = (
            "Voltage setting = %.3f V\n"
            "Current setting = %.3f A\n"
            % (voltage, current))
        # print(msg)
        return msg, voltage, current

    def check_output(self):
        """Return the output status."""
        self.clean_serial()
        self.ser.write("OUTP?\n\r")
        self.wait()
        try:
            val = int(self.ser.readline())
        except ValueError:
            val = -999
            msg = 'WARNING! Could not get correct output value! | Response = "%s"' % (val)
            print(msg)
            return msg, val
        if val == 0:
            msg = "Measured output state = OFF"
        elif val == 1:
            msg = "Measured output state = ON"
        else:
            msg = "Failed to measure output..."
        # print(msg)
        return msg, val

    def set_voltage(self, val, silent=False):
        """Set the PMX voltage."""
        self.clean_serial()
        self.ser.write("VOLT %f\n\r" % (float(val)))
        self.wait()
        self.ser.write("VOLT?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Voltage set = %.3f V" % (float(val))
        if silent is not True:
            print(msg)

        return msg

    def set_current(self, val, silent=False):
        """Set the PMX on."""
        self.clean_serial()
        self.ser.write("CURR %f\n\r" % (float(val)))
        self.wait()
        self.ser.write("CURR?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Current set = %.3f A\n" % (float(val))
        if silent is not True:
            print(msg)

        return msg

    def use_external_voltage(self):
        """Set PMX to use external voltage."""
        self.clean_serial()
        self.ser.write("VOLT:EXT:SOUR VOLT\n\r")
        self.wait()
        self.ser.write("VOLT:EXT:SOUR?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "External source = %s" % (val)
        print(msg)

        return msg

    def ign_external_voltage(self):
        """Set PMX to ignore external voltage."""
        self.clean_serial()
        self.ser.write("VOLT:EXT:SOUR NONE\n\r")
        self.wait()
        self.ser.write("VOLT:EXT:SOUR?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "External source = %s" % (val)
        print(msg)

        return msg

    def set_voltage_limit(self, val, silent=False):
        """Set the PMX voltage limit."""
        self.clean_serial()
        self.ser.write("VOLT:PROT %f\n\r" % (float(val)))
        self.wait()
        self.ser.write("VOLT:PROT?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Voltage limit set = %.3f V" % (float(val))
        if silent is not True:
            print(msg)

        return msg

    def set_current_limit(self, val, silent=False):
        """Set the PMX current limit."""
        self.clean_serial()
        self.ser.write("CURR:PROT %f\n\r" % (float(val)))
        self.wait()
        self.ser.write("CURR:PROT?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Current limit set = %.3f A\n" % (float(val))
        if silent is not True:
            print(msg)

        return msg

    def turn_on(self):
        """Turn the PMX on."""
        self.clean_serial()
        self.ser.write("OUTP ON\n\r")
        self.wait()
        self.ser.write("OUTP?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Output state = %s" % (val)
        print(msg)

        return msg

    def turn_off(self):
        """Turn the PMX off."""
        self.clean_serial()
        self.ser.write("OUTP OFF\n\r")
        self.wait()
        self.ser.write("OUTP?\n\r")
        self.wait()
        val = self.ser.readline()
        msg = "Output state = %s" % (val)
        print(msg)

        return msg

    # ***** Helper Methods *****
    def __conn(self, rtu_port=None, tcp_ip=None, tcp_port=None, timeout=None):
        """Connect to the PMX module.

        Args:
            rtu_port (str): Serial RTU port
            tcp_ip (str): TCP IP address
            tcp_port (int): TCP port
            timeout (int): Connection timeout
        """
        if rtu_port is None and (tcp_ip is None or tcp_port is None):
            raise Exception(
                "Aborted PMX._conn() due to no RTU or "
                "TCP port specified")
        elif (rtu_port is not None
              and (tcp_ip is not None or tcp_port is not None)):
            raise Exception(
                "Aborted PMX._conn() due to RTU and TCP port both being "
                "specified. Can only have one or the other.")
        elif rtu_port is not None:
            self.ser = serial.Serial(
                port=rtu_port, baudrate=19200, bytesize=8,
                parity='N', stopbits=1, timeout=timeout)
            self._rtu_port = rtu_port
            self.using_tcp = False
            msg = "Connected to RTU port %s" % (rtu_port)
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout)
            self._tcp_ip = tcp_ip
            self._tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = "Connected to TCP IP %s at port %d" % (tcp_ip, tcp_port)
        else:
            raise Exception(
                "Aborted PMX._conn() due to unknown error")
        return msg

    def wait(self):
        """Sleep."""
        time.sleep(0.05)
        return True

    def clean_serial(self):
        """Flush the serial buffer."""
        # if not False:
        #    self.ser.reset_input_buffer()
        #    self.ser.reset_output_buffer()
        #    self.ser.flush()
        # else:
        # self.ser.flushInput()
        self.ser.flushInput()
        return True

    def _remote_Mode(self):
        """Enable remote control."""
        self.clean_serial()
        self.ser.write('SYST:REM\n\r')
        self.wait()
        return True


class Command:
    """The Command object is used to command the PMX.

    Args:
        PMX (PMX): PMX object

    """

    def __init__(self, input_PMX):
        # PMX connection
        if input_PMX is not None:
            self._PMX = input_PMX
        else:
            raise Exception(
                "PMX object not passed to Command constructor\n")

        # Dict of commands
        self._cmds = {
            "set_port": "P",
            "check_v": "V?",
            "check_c": "C?",
            "check_vc": "VC?",
            "check_vs": "VS?",
            "check_cs": "CS?",
            "check_vcs": "VCS?",
            "check_out": "O?",
            "set_v": "V",
            "set_c": "C",
            "set_v_lim": "VL",
            "set_c_lim": "CL",
            "set_on": "ON",
            "set_off": "OFF",
            "get_help": "H",
            "use_ext": "U",
            "ign_ext": "I",
            "stop": "Q"}

    def get_help(self):
        """Print possible commands."""
        wrstr = (
            "\nChange ttyUSB port = '%s'\n"
            "Check output voltage = '%s'\n"
            "Check output current = '%s'\n"
            "Check output voltage and current = '%s'\n"
            "Check voltage setting = '%s'\n"
            "Check current setting = '%s'\n"
            "Check voltage and current setting = '%s'\n"
            "Check output state = '%s'\n"
            "Set output voltage = '%s' [setting]\n"
            "Set output current = '%s' [setting]\n"
            "Set output voltage limit = '%s'\n"
            "Set output current limit = '%s'\n"
            "Turn output on = '%s'\n"
            "Turn output off = '%s'\n"
            "Print possible commands = '%s'\n"
            "Use external voltage = '%s'\n"
            "Ignore external voltage = '%s'\n"
            "Quit program = '%s'\n"
            % (self._cmds["set_port"],
               self._cmds["check_v"],
               self._cmds["check_c"],
               self._cmds["check_vc"],
               self._cmds["check_vs"],
               self._cmds["check_cs"],
               self._cmds["check_vcs"],
               self._cmds["check_out"],
               self._cmds["set_v"],
               self._cmds["set_c"],
               self._cmds["set_v_lim"],
               self._cmds["set_c_lim"],
               self._cmds["set_on"],
               self._cmds["set_off"],
               self._cmds["get_help"],
               self._cmds["use_ext"],
               self._cmds["ign_ext"],
               self._cmds["stop"]))
        return wrstr

    def user_input(self, arg):
        """Take user input and execute PMX command."""
        argv = arg.split()
        # if len(args) > 0:
        # value = float(args[0])

        while len(argv):
            cmd = str(argv.pop(0)).upper()
            # No command
            if cmd == '':
                return
            # Check voltage
            elif cmd == self._cmds["check_v"]:
                return self._PMX.check_voltage()
            # Check current
            elif cmd == self._cmds["check_c"]:
                return self._PMX.check_current()
            # Check voltage and current
            elif cmd == self._cmds["check_vc"]:
                return self._PMX.check_voltage_current()
            # Check voltage setting
            elif cmd == self._cmds["check_vs"]:
                return self._PMX.check_voltage_setting()
            # Check current setting
            elif cmd == self._cmds["check_cs"]:
                return self._PMX.check_current_setting()
            # Check voltage and current
            elif cmd == self._cmds["check_vcs"]:
                return self._PMX.check_voltage_current_setting()
            # Check output state
            elif cmd == self._cmds["check_out"]:
                return self._PMX.check_output()
            # Turn output state ON
            elif cmd == self._cmds["set_on"]:
                return self._PMX.turn_on()
            # Turn output state OFF
            elif cmd == self._cmds["set_off"]:
                return self._PMX.turn_off()
            # Get HELP

            # elif cmd == self._cmds["set_v"]:
                # print(value)
                # ret = self._PMX.set_voltage(value)

            # elif cmd == self._cmds["set_c"]:
                # ret = self._PMX.set_current(value)

            elif cmd == self._cmds["use_ext"]:
                return self._PMX.use_external_voltage()
            elif cmd == self._cmds["ign_ext"]:
                return self._PMX.ign_external_voltage()
            elif cmd == self._cmds["get_help"]:
                ret = self.get_help()
                print(ret)
            # Exit the program
            elif cmd == self._cmds["stop"]:
                sys.exit("\nExiting...")
            # Set the RTU port
            elif cmd == self._cmds["set_port"]:
                if self._PMX.using_tcp:
                    print("Connected via TCP rather than RTU. Cannot set RTU port")
                    return False
                set_val = self._int(argv.pop(0))
                if set_val is not None:
                    del self._PMX
                    self._PMX = PMX(set_val)
                else:
                    return False
            elif cmd == self._cmds["set_v"]:
                set_val = self._float(argv.pop(0))
                if set_val is not None:
                    self._PMX.set_voltage(set_val)
                else:
                    return False
            elif cmd.lower() == self._cmds["set_c"].lower():
                set_val = self._float(argv.pop(0))
                if set_val is not None:
                    self._PMX.set_current(set_val)
                else:
                    return False
            elif cmd == self._cmds["set_v_lim"]:
                set_val = self._float(argv.pop(0))
                if set_val is not None:
                    self._PMX.set_voltage_limit(set_val)
                else:
                    return False
            elif cmd.lower() == self._cmds["set_c_lim"].lower():
                set_val = self._float(argv.pop(0))
                if set_val is not None:
                    self._PMX.set_current_limit(set_val)
                else:
                    return False
            else:
                print("Command '%s' not understood..." % (cmd))
                return False
        return True

    # ***** Helper Methods *****
    def _float(self, val):
        """Try to convert a value to a float."""
        try:
            return float(val)
        except ValueError:
            print("Input '%s' not understood, must be a float..." % (val))
            return None

    def _int(self, val):
        """Try to convert a value to an int."""
        try:
            return int(val)
        except ValueError:
            print("Input '%s' not understood, must be a int..." % (val))
            return None
