class JXC831:
    """
    JXC831 object is for reading and writing addresses on the
    JXC actuator controller and inherits a BBB object, which is used
    to actually control the pin voltages.

    Args:
    BBB (src.BBB): inherited BBB object
    """
    def __init__(self, BBB):
        if BBB is None:
            raise Exception(
                'JXC831 Exception: SMC controller requires a BBB interface '
                'to be passed to JXC831() constructor')
        self.BBB = BBB

        # Number of attempts for each read/write command,
        # because sometimes they fail for no obvious reason...
        self.num_attempts = 5

        # Assign SMC controller pins to BBB pins. Also listed are the I/O
        # Read/write -- controllable by the user
        self.IN0 = self.BBB.GPIO_22
        self.IN1 = self.BBB.GPIO_23
        self.IN2 = self.BBB.GPIO_26
        self.IN3 = self.BBB.GPIO_27
        self.IN4 = self.BBB.GPIO_34

        self.SETUP = self.BBB.GPIO_35
        self.HOLD = self.BBB.GPIO_38
        self.DRIVE = self.BBB.GPIO_39
        self.RESET = self.BBB.GPIO_46
        self.SVON = self.BBB.GPIO_47

        self.BRAKE1 = self.BBB.GPIO_65
        self.BRAKE2 = self.BBB.GPIO_67
        self.BRAKE3 = self.BBB.GPIO_69

        self.EMG1 = self.BBB.GPIO_61
        self.EMG2 = self.BBB.GPIO_66
        self.EMG3 = self.BBB.GPIO_68

        # Read only -- not controllable by the user
        self.OUT0 = self.BBB.GPIO_2
        self.OUT1 = self.BBB.GPIO_3
        self.OUT2 = self.BBB.GPIO_4
        self.OUT3 = self.BBB.GPIO_5
        self.OUT4 = self.BBB.GPIO_15

        self.BUSY = self.BBB.GPIO_50
        self.AREA = self.BBB.GPIO_51
        self.SETON = self.BBB.GPIO_60

        self.INP = self.BBB.GPIO_30
        self.SVRE = self.BBB.GPIO_31
        self.ESTOP = self.BBB.GPIO_48
        self.ALARM = self.BBB.GPIO_49

        self.ACT1 = self.BBB.GPIO_20
        self.ACT2 = self.BBB.GPIO_117
        self.ACT3 = self.BBB.GPIO_14

    # ***** Public Methods *****
    def read(self, addr):
        """
        Read JXC address

        Args:
        addr (int): address to be read
        """
        for n in range(self.num_attempts):
            try:
                return self.BBB.read_pin(addr)
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
                return self.BBB.set_pin_on(addr)
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
                return self.BBB.set_pin_off(addr)
            except:
                continue
        return Exception(
            'JXC831 Exception: Cannot write to pin at address', addr)

