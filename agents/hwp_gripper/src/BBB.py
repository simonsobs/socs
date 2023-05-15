# Built-in python modules
import Adafruit_BBIO.GPIO as gpio

class BBB:
    def __init__(self):
        # Read/write -- controllable by user
        self.GPIO_22 = 'P8_19'
        gpio.setup(self.GPIO_22, gpio.OUT)
        self.GPIO_23 = 'P8_13'
        gpio.setup(self.GPIO_23, gpio.OUT)
        self.GPIO_26 = 'P8_14'
        gpio.setup(self.GPIO_26, gpio.OUT)
        self.GPIO_27 = 'P8_17'
        gpio.setup(self.GPIO_27, gpio.OUT)
        self.GPIO_34 = 'P8_5'
        gpio.setup(self.GPIO_34, gpio.OUT)
        self.GPIO_35 = 'P8_6'
        gpio.setup(self.GPIO_35, gpio.OUT)
        self.GPIO_38 = 'P8_3'
        gpio.setup(self.GPIO_38, gpio.OUT)
        self.GPIO_39 = 'P8_4'
        gpio.setup(self.GPIO_39, gpio.OUT)
        self.GPIO_46 = 'P8_16'
        gpio.setup(self.GPIO_46, gpio.OUT)
        self.GPIO_47 = 'P8_15'
        gpio.setup(self.GPIO_47, gpio.OUT)
        self.GPIO_61 = 'P8_26'
        gpio.setup(self.GPIO_61, gpio.OUT)
        self.GPIO_65 = 'P8_18'
        gpio.setup(self.GPIO_65, gpio.OUT)
        self.GPIO_66 = 'P8_7'
        gpio.setup(self.GPIO_66, gpio.OUT)
        self.GPIO_67 = 'P8_8'
        gpio.setup(self.GPIO_67, gpio.OUT)
        self.GPIO_68 = 'P8_10'
        gpio.setup(self.GPIO_68, gpio.OUT)
        self.GPIO_69 = 'P8_9'
        gpio.setup(self.GPIO_69, gpio.OUT)

        # Read only -- not controllable by user
        self.GPIO_2 = 'P9_22'
        gpio.setup(self.GPIO_2, gpio.IN)
        self.GPIO_3 = 'P9_21'
        gpio.setup(self.GPIO_3, gpio.IN)
        self.GPIO_4 = 'P9_18'
        gpio.setup(self.GPIO_4, gpio.IN)
        self.GPIO_5 = 'P9_17'
        gpio.setup(self.GPIO_5, gpio.IN)
        self.GPIO_14 = 'P9_26'
        gpio.setup(self.GPIO_14, gpio.IN)
        self.GPIO_15 = 'P9_24'
        gpio.setup(self.GPIO_15, gpio.IN)
        self.GPIO_20 = 'P9_41'
        gpio.setup(self.GPIO_20, gpio.IN)
        self.GPIO_50 = 'P9_14'
        gpio.setup(self.GPIO_50, gpio.IN)
        self.GPIO_51 = 'P9_16'
        gpio.setup(self.GPIO_51, gpio.IN)
        self.GPIO_60 = 'P9_12'
        gpio.setup(self.GPIO_60, gpio.IN)
        self.GPIO_30 = 'P9_11'
        gpio.setup(self.GPIO_30, gpio.IN)
        self.GPIO_31 = 'P9_13'
        gpio.setup(self.GPIO_31, gpio.IN)
        self.GPIO_48 = 'P9_15'
        gpio.setup(self.GPIO_48, gpio.IN)
        self.GPIO_49 = 'P9_23'
        gpio.setup(self.GPIO_49, gpio.IN)
        self.GPIO_117 = 'P9_25'
        gpio.setup(self.GPIO_117, gpio.IN)

    def __del__(self):
        gpio.cleanup()

    # ***** Public Methods *****
    def read_pin(self, addr):
        """
        Read BBB pin

        Args:
        addr (str): BBB pin address from which to read
        """
        return gpio.input(addr)

    def set_pin_on(self, addr):
        """
        Set BBB pin to on

        Args:
        addr (str): BBB pin address from which to read
        """
        return gpio.output(addr, gpio.HIGH)

    def set_pin_off(self, addr):
        """
        Set BBB pin to off

        Args:
        addr (str): BBB pin address from which to read
        """
        return gpio.output(addr, gpio.LOW)

