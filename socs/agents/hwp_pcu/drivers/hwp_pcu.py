import time

import serial


class PCU:
    """Class to communicate with the phase compensation unit.

    Args:
        port (str): Path to USB device in '/dev/'

    Attributes:
        status (str): The status of the unit (off/on_1/on_2/stop)
    """

    def __init__(self, port):
        self.port = serial.Serial(
            port,
            baudrate=19200,
            timeout=10,
        )

    def close(self):
        self.port.close()

    def relay_on(self, channel):
        cmd = "relay on " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        time.sleep(.1)

    def relay_off(self, channel):
        cmd = "relay off " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        time.sleep(.1)

    def relay_read(self, channel):
        cmd = "relay read " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        time.sleep(.1)
        response = self.port.read(25)
        time.sleep(.1)
        response = response.decode('utf-8')
        if response.find("on") > 0:
            return True
        elif response.find("off") > 0:
            return False
        else:
            return -1

    def get_status(self):
        """get_status()

        **Task** - Get the operation mode of the phase compensation unit.
        off: The compensation phase is zero.
        on_1: The compensation phase is +120 deg.
        on_2: The compensation phase is -120 deg.
        stop: Stop the HWP spin.
        """
        channel = [0, 1, 2, 5, 6, 7]
        channel_switch = []

        for i in channel:
            channel_switch.append(self.relay_read(i))
        if channel_switch == [False, False, False, False, False, False]:
            return 'off'
        elif channel_switch == [True, True, True, False, False, False]:
            return 'on_1'
        elif channel_switch == [True, True, True, True, True, True]:
            return 'on_2'
        elif channel_switch == [False, True, True, True, False, False]:
            return 'stop'
        elif -1 in channel_switch:
            return 'failed'
        else:
            return 'undefined'
