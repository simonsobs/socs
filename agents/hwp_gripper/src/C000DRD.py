# Built-in python modules
import serial
from pymodbus.client.sync import ModbusSerialClient
from pymodbus.client.sync import ModbusTcpClient
from pymodbus.transaction import ModbusRtuFramer


class C000DRD:
    """
    The C000DRD object is for controlling the C0-00DR-D Click PLC
    control module, as well as any auxilliary modules connected to it.
    It handles the low-level interface to the switches on the PLC,
    which then can be inherited by higher-level control classes.

    Args:
    rtu_port (int): Modbus serial port (defualt None).
    tcp_ip (str): TCP IP address (default None)
    tcp_port (int): TCP IP port (default None)

    Only either rtu_port or tcp_ip + tcp_port can be defined.
    """
    def __init__(self, rtu_port=None, tcp_ip=None, tcp_port=None):
        # Connect to device
        self._conn(rtu_port, tcp_ip, tcp_port)

        # Private variables
        self._count = 1  # Number of bytes to read -- defaults to 1
        self._unit = 1  # ID of the slave -- always 1 for the CHWP gripper

        # Click PLC Addresses as shown in the Windows software
        # Hardware configuration from right to left:
        # C0-00DR-D : C0-08TR : C0-16NE3

        # Unit 00 = C0-00DR-D
        # Read only -- not controllable by user
        self.X001 = 100001
        self.X002 = 100002
        self.X003 = 100003
        self.X004 = 100004
        self.X005 = 100005
        self.X006 = 100006
        self.X007 = 100007
        self.X008 = 100008
        # Read/write -- controllable by user
        self.Y001 = 8192
        self.Y002 = 8193
        self.Y003 = 8194
        self.Y004 = 8195
        self.Y005 = 8196
        self.Y006 = 8197

        # Unit 10 = C0-08TR
        # Read/write -- controllable by user
        self.Y101 = 8224
        self.Y102 = 8225
        self.Y103 = 8226
        self.Y104 = 8227
        self.Y105 = 8228
        self.Y106 = 8229
        self.Y107 = 8230
        self.Y108 = 8231

        # Unit 20 = C0-16NE3
        # Read only -- not controllable by user
        self.X201 = 100065
        self.X202 = 100066
        self.X203 = 100067
        self.X204 = 100068
        self.X205 = 100069
        self.X206 = 100070
        self.X207 = 100071
        self.X208 = 100072
        self.X209 = 100073
        self.X210 = 100074
        self.X211 = 100075
        self.X212 = 100076
        self.X213 = 100077
        self.X214 = 100078
        self.X215 = 100079
        self.X216 = 100080

    def __del__(self):
        self.client.close()
        del self.client

    # ***** Public Methods *****
    def read_pin(self, addr):
        """
        Read PLC switch

        Args:
        addr (int): PLC address from which to read
        """
        return self.client.read_discrete_inputs(
            self._addr(addr), self._count, unit=self._unit).bits[0]

    def set_pin_on(self, addr):
        """
        Set PLC switch to on

        Args:
        addr (int): PLC address from which to read
        """
        return self.client.write_coils(
            self._addr(addr), [True], unit=self._unit)

    def set_pin_off(self, addr):
        """
        Set PLC switch to off

        Args:
        addr (int): PLC address from which to read
        """
        return self.client.write_coils(
            self._addr(addr), [False], unit=self._unit)

    def toggle_pin(self, addr):
        """
        Toggle PLC switch

        Args:
        addr (int): PLC address from which to read
        """
        return self.client.write_coils(
            self._addr(addr), [not self.read_pin(addr)], unit=self._unit)

    # ***** Helper Methods *****
    def _addr(self, addr):
        """ Convert provided address to correct Modbus address """
        if addr > 65535:
            return addr - 100000 - 1
        else:
            return addr

    def _conn(self, rtu_port=None, tcp_ip=None, tcp_port=None):
        """
        Connect to the device using either TCP or RTU. If using
        TCP, use an RTU framer to emulate serial at the PLC.
        """
        if rtu_port is None and (
           tcp_ip is None or tcp_port is None):
            raise Exception('C000DRD Exception: no RTU or TCP port specified')
        elif rtu_port is not None and (
           tcp_ip is not None or tcp_port is not None):
            raise Exception(
                'C000DRD Exception: RTU and TCP port specified. '
                'Can only have one or the other.')
        elif rtu_port is not None:
            self.client = ModbusSerialClient(
                method='rtu', port=rtu_port, baudrate=38400,
                timeout=0.1, parity=serial.PARITY_ODD)
            self.conn = self.client.connect()
        elif tcp_ip is not None and tcp_port is not None:
            self.client = ModbusTcpClient(
                tcp_ip, port=int(tcp_port), baudrate=38400,
                timeout=0.1, parity=serial.PARITY_ODD, framer=ModbusRtuFramer)
            self.conn = self.client.connect()
