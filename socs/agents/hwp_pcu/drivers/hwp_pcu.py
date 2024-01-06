import time

import serial

patterns = {
    'off': [0, 0, 0, 0, 0, 0],
    'on_1': [1, 1, 1, 0, 0, 0],
    'on_2': [1, 1, 1, 1, 1, 1],
    'stop': [0, 1, 1, 1, 0, 0],
}


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
            timeout=1,
            bytesize=serial.EIGHTBITS,
            stopbits=serial.STOPBITS_ONE,
        )

    def close(self):
        self.port.close()

    def sleep(self):
        time.sleep(0.1)

    def read(self):
        return self.port.read_until(b'\n\r').strip().decode()

    def clear_buffer(self):
        while True:
            res = self.read()
            if len(res) == 0:
                break

    def relay_on(self, channel):
        cmd = "relay on " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        self.sleep()

    def relay_off(self, channel):
        cmd = "relay off " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        self.sleep()

    def relay_read(self, channel):
        cmd = "relay read " + str(channel) + "\n\r"
        self.port.write(cmd.encode('utf-8'))
        self.sleep()
        response = self.read()
        response = self.read()
        if response == "on":
            return 1
        elif response == "off":
            return 0
        else:
            return -1

    def send_command(self, command):
        pattern = patterns[command]
        for i, p in zip([0, 1, 2, 5, 6, 7], pattern):
            if p:
                self.relay_on(i)
            else:
                self.relay_off(i)
            self.sleep()
            self.read()

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
        if -1 in channel_switch:
            return 'failed'
        for command, pattern in patterns.items():
            if channel_switch == pattern:
                return command
        return 'undefined'
