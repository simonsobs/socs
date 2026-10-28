# Code developed with AI assistance.
# Built-in python modules
import re
import time as tm

# Control modules
from socs.common import moxa_serial as mx


class SLP2:
    """
    The SLP2 object is for communicating with the Pacico SLP2 inclinometer

    Args:
    tcp_ip (str): TCP IP address
    tcp_port (int): TCP port
    """
    waittime = 0.05  # sec
    read_timeout = 2.0  # sec, max time to wait for a CR-terminated reply

    # ASCII commands terminated by CR
    command_stop_cont = b'stpcasc\r'  # stop continuous ASCII output
    command_ascii = b'setoasc\r'  # output format = ASCII
    command_angle = b'get-x&y\r'  # -> +xxx.xxx,+yyy.yyy<CR>
    command_temp = b'gettemp\r'  # -> +tt.t<CR> (ADC bytes may precede it)
    # Zero-point commands (setzcur / setzfac) are intentionally NOT
    # implemented, because they change the sensor's stored state.

    num_re = re.compile(rb'[+-]?\d+\.\d+')

    def __init__(self, tcp_ip=None, tcp_port=None, timeout=None, verbose=0):
        self.tcp_ip = tcp_ip
        self.tcp_port = tcp_port
        self.verbose = verbose

        # Connect to device
        msg = self.__conn(tcp_ip, tcp_port, timeout)
        print(msg)

    def __del__(self):
        print(f"Disconnecting from TCP IP {self.tcp_ip} at port {self.tcp_port}")
        self.ser.sock.close()
        return

    def get_angle(self):
        """ Measure the two-axis angle """
        read = self.query(self.command_angle)
        nums = [float(x) for x in self.num_re.findall(read)]
        if len(nums) < 2:
            msg = f'Failed to parse the angles from the reply: {read!r}'
            raise ValueError(msg)
        val = (nums[0], nums[1])
        msg = f"Measured angle: X = {val[0]}, Y = {val[1]}"
        if self.verbose > 0:
            print(msg)
        return msg, val

    def get_temp(self):
        """ Measure the temperature (common to both axes) """
        read = self.query(self.command_temp)
        nums = [float(x) for x in self.num_re.findall(read)]
        if len(nums) < 1:
            msg = f'Failed to parse the temperature from the reply: {read!r}'
            raise ValueError(msg)
        # ADC bytes may precede the temperature, so use the last number
        val = nums[-1]
        msg = f"Measured temperature = {val}"
        if self.verbose > 0:
            print(msg)
        return msg, val

    def query(self, command):
        """ Send a command and read the reply until CR following a number """
        self.clean_serial()
        if self.verbose > 0:
            print(f'command = {command}')
        self.ser.write(command)
        read = b''
        t_end = tm.time() + self.read_timeout
        while tm.time() < t_end:
            c = self.ser.readexactly(1)
            if not c:
                continue
            # binary ADC bytes may contain CR, so stop only after a number
            if c == b'\r' and self.num_re.search(read):
                break
            read += c
        if self.verbose > 0:
            print(f'read = {read}')
        return read

    # ***** Helper Methods *****
    def __conn(self, tcp_ip=None, tcp_port=None, timeout=None):
        """
        Connect to the tilt sensor module

        Args:
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
        """
        if tcp_ip is None or tcp_port is None:
            raise Exception(
                "Aborted SLP2._conn() due to no "
                "TCP port specified")
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout, encoded=False)
            self.tcp_ip = tcp_ip
            self.tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = f"Connected to TCP IP {tcp_ip} at port {tcp_port}"
            # Make sure continuous output is off, then set ASCII output mode.
            # The replies (e.g. b"OK" without CR) are discarded.
            for command in [self.command_stop_cont, self.command_ascii]:
                if self.verbose > 0:
                    print(f'initialization command = {command}')
                self.ser.write(command)
                tm.sleep(0.5)
                self.clean_serial()
        else:
            raise Exception(
                "Aborted SLP2._conn() due to unknown error")
        return msg

    def wait(self):
        """ Sleep """
        tm.sleep(self.waittime)
        return True

    def clean_serial(self):
        """ Flush the serial buffer """
        self.ser.flushInput()
        self.wait()
        return True
