class JXC831:
    """
    JXC831 object is for reading and writing addresses on the
    JXC actuator controller and inherits a PLC object, which is used
    to actually control the pin voltages.

    Args:
    PLC (src.C000DRD): inherited PLC object
    """
    def __init__(self, PLC):
        if PLC is None:
            raise Exception(
                'JXC831 Exception: SMC controller requires a PLC interface '
                'to be passed to JXC831() constructor')
        self.PLC = PLC

        # Number of attempts for each read/write command,
        # because sometimes they fail for no obvious reason...
        self.num_attempts = 5

        # Assign SMC controller pins to PLC pins. Also listed are the I/O
        # cable wire colors for the connections
        # Read/write -- controllable by the user
        self.IN0 = self.PLC.Y001
        self.IN1 = self.PLC.Y002
        self.IN2 = self.PLC.Y003
        self.IN3 = self.PLC.Y004
        self.IN4 = self.PLC.Y005

        self.SETUP = self.PLC.Y006
        self.HOLD = self.PLC.Y101
        self.DRIVE = self.PLC.Y102
        self.RESET = self.PLC.Y103
        self.SVON = self.PLC.Y104

        self.BRAKE1 = self.PLC.Y106
        self.BRAKE2 = self.PLC.Y107
        self.BRAKE3 = self.PLC.Y108

        # Read only -- not controllable by the user
        self.OUT0 = self.PLC.X001
        self.OUT1 = self.PLC.X002
        self.OUT2 = self.PLC.X003
        self.OUT3 = self.PLC.X004
        self.OUT4 = self.PLC.X005

        self.BUSY = self.PLC.X006
        self.AREA = self.PLC.X007
        self.SETON = self.PLC.X008

        self.INP = self.PLC.X201
        self.SVRE = self.PLC.X202
        self.ESTOP = self.PLC.X203
        self.ALARM = self.PLC.X204

        self.BUSY1 = self.PLC.X205
        self.BUSY2 = self.PLC.X206
        self.BUSY3 = self.PLC.X207

        self.AREA1 = self.PLC.X208
        self.AREA2 = self.PLC.X209
        self.AREA3 = self.PLC.X210

        self.INP1 = self.PLC.X211
        self.INP2 = self.PLC.X212
        self.INP3 = self.PLC.X213

        self.ALARM1 = self.PLC.X214
        self.ALARM2 = self.PLC.X215
        self.ALARM3 = self.PLC.X216

    # ***** Public Methods *****
    def read(self, addr):
        """
        Read JXC address

        Args:
        addr (int): address to be read
        """
        for n in range(self.num_attempts):
            try:
                return self.PLC.read_pin(addr)
            except:
                continue
        raise Exception(
            'JXC831 Exception: Cannot read pin at address', addr)

    def set_on(self, addr):
        """
        Set JXC address value to ON

        Args:
        addr (int): address to be set on
        """
        for n in range(self.num_attempts):
            try:
                return self.PLC.set_pin_on(addr)
            except:
                continue
        return Exception(
            'JXC831 Exception: Cannot write to pin at address', addr)

    def set_off(self, addr):
        """
        Set JXC address value to OFF

        Args:
        addr (int): address to be set off
        """
        for n in range(self.num_attempts):
            try:
                return self.PLC.set_pin_off(addr)
            except:
                continue
        return Exception(
            'JXC831 Exception: Cannot write to pin at address', addr)

    def toggle(self, addr):
        """
        Toggle JXC address value

        Args:
        addr (int): address to be toggled
        """
        for n in range(self.num_attempts):
            try:
                return self.PLC.toggle_pin(addr)
            except:
                continue
        return Exception(
            'JXC831 Exception: Cannot read/write to pin at address', addr)
