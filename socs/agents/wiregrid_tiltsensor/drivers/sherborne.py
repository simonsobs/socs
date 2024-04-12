import time as tm

import serial as sr

# Control modules
from socs.common import moxa_serial as mx


class Sherborne:
    """
    The sherborne object is for communicating with the sherborne gravity sensor

    Args:
    rtu_port (str): Serial RTU port
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

    def __init__(self, rtu_port=None, tcp_ip=None, tcp_port=None, timeout=None, reset_boot=False, verbose=0):
        self.verbose = verbose
        # Connect to device
        msg = self.__conn(rtu_port, tcp_ip, tcp_port, timeout)
        print(msg)
        if reset_boot:
            self.reset()

    def __del__(self):
        if not self.using_tcp:
            print(
                f"Disconnecting from RTU port {self._rtu_port}")
            self.ser.close()
        else:
            print(
                f"Disconnecting from TCP IP {self._tcp_ip} at port {self._tcp_port}")
            pass
        return

    def get_angle(self):
        """ Measure the two-axis angle """
        self.clean_serial()
        if self.verbose > 0:
            print(f'get_angle() commands = {self.command_angleX}, {self.command_angleY}')
            pass
        SIZE = 16
        self.ser.write(self.command_angleX)
        read_angleX = self.ser.read(SIZE)
        value_read_angleX = read_angleX.decode('ascii')
        value_read_angleX = value_read_angleX.replace('\r', '')
        if self.verbose > 0:
            print(f'read_angleX = {value_read_angleX}')
            pass
        self.ser.write(self.command_angleY)
        read_angleY = self.ser.read(SIZE)
        value_read_angleY = read_angleY.decode('ascii')
        value_read_angleY = value_read_angleY.replace('\r', '')
        if self.verbose > 0:
            print(f'read_angleY = {value_read_angleY}')
            pass
        self.wait()

        val = (value_read_angleX, value_read_angleY)
        msg = f"Measured angle: X = {value_read_angleX}, Y = {value_read_angleY}"
        if self.verbose > 0:
            print(msg)
            pass
        return msg, val

    def __conn(self, rtu_port, tcp_ip, tcp_port, timeout):
        """
        Connect to the PMX module

        Args:
        rtu_port (str): Serial RTU port
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
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
            self.ser = sr.Serial(
                port=rtu_port, baudrate=115200, bytesize=8,
                parity=None, stopbits=1, timeout=timeout)
            self.rtu_port = rtu_port
            self.using_tcp = False
            msg = "Connected to RTU port %s" % (rtu_port)
        elif tcp_ip is not None and tcp_port is not None:
            self.ser = mx.Serial_TCPServer((tcp_ip, tcp_port), timeout)
            self.tcp_ip = tcp_ip
            self.tcp_port = int(tcp_port)
            self.using_tcp = True
            msg = "Connected to TCP IP %s at port %d" % (tcp_ip, tcp_port)
        else:
            raise Exception(
                "Aborted PMX._conn() due to unknown error")
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
