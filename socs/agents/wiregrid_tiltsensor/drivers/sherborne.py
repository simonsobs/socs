import time as tm

# Control modules
from socs.common import moxa_serial as mx


class Sherborne:
    """
    The sherborne object is for communicating with the sherborne tilt sensor

    Args:
    tcp_ip (str): TCP IP address
    tcp_port (int): TCP port
    """
    waittime = 0.05  # sec
    waittime_reset = 30  # sec, this is the time for the sensor to reset. should be over 30 sec
    address_Xaxis = 148  # default address of Xaxis is 148. this has individual sensor difference.
    address_Yaxis = 149  # default address of Yaxis is 149. this has individual sensor difference.

    command_angleX = b'!' + str(address_Xaxis).encode('ascii') + b':SYS?\r'
    command_angleY = b'!' + str(address_Yaxis).encode('ascii') + b':SYS?\r'
    command_resetX = b'!' + str(address_Xaxis).encode('ascii') + b':RST\r'
    command_resetY = b'!' + str(address_Yaxis).encode('ascii') + b':RST\r'

    def __init__(self, tcp_ip=None, tcp_port=None, timeout=None, reset_boot=False, verbose=0):
        self.tcp_ip = tcp_ip
        self.tcp_port = tcp_port
        self.verbose = verbose

        # Connect to device
        msg = self.__conn(tcp_ip, tcp_port, timeout)
        print(msg)
        if reset_boot:
            self.reset()

    def __del__(self):
        print(f"Disconnecting from TCP IP {self.tcp_ip} at port {self.tcp_port}")
        self.ser.close()
        return

    def get_angle(self):
        """ Measure the two-axis angle """
        self.clean_serial()
        if self.verbose > 0:
            print(f'get_angle() commands = {self.command_angleX}, {self.command_angleY}')
        SIZE = 16
        self.ser.write(self.command_angleX)
        read_angleX = self.ser.read(SIZE)
        value_read_angleX = read_angleX.decode('ascii')
        value_read_angleX = value_read_angleX.replace('\r', '')
        if self.verbose > 0:
            print(f'read_angleX = {value_read_angleX}')
        self.ser.write(self.command_angleY)
        read_angleY = self.ser.read(SIZE)
        value_read_angleY = read_angleY.decode('ascii')
        value_read_angleY = value_read_angleY.replace('\r', '')
        if self.verbose > 0:
            print(f'read_angleY = {value_read_angleY}')

        self.wait()

        val = (value_read_angleX, value_read_angleY)
        msg = f"Measured angle: X = {value_read_angleX}, Y = {value_read_angleY}"
        if self.verbose > 0:
            print(msg)

        return msg, val

    def __conn(self, tcp_ip, tcp_port, timeout):
        """
        Connect to the tilt sensor module

        Args:
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
        """
        if tcp_ip is None or tcp_port is None:
            raise Exception(
                "Aborted Sherborne._conn() due to no TCP IP or "
                "TCP port specified")
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout, encoded=False)
            self.tcp_ip = tcp_ip
            self.tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = f"Connected to TCP IP {tcp_ip} at port {tcp_port}"
        else:
            raise Exception(
                "Aborted Sherborne._conn() due to unknown error")
        return msg

    def wait(self):
        """ Sleep """
        tm.sleep(self.waittime)
        return True

    def wait_reset(self):
        """ Sleep for the reset time """
        tm.sleep(self.waittime_reset)
        return True

    def clean_serial(self):
        """ Flush the serial buffer """
        self.ser.flushInput()
        return True

    def reset(self):
        """ reset the tilt sensor """
        self.ser.write(self.command_resetX)
        readX = self.ser.read(2)
        if self.verbose > 0:
            print(readX)
        self.ser.write(self.command_resetY)
        readY = self.ser.read(2)
        if self.verbose > 0:
            print(readY)
        self.wait_reset()
        return True
