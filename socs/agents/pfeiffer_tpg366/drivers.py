# Original script by Zhilei Xu and Tanay Bhandarkar.

import numpy as np

from socs.tcp import TCPInterface

BUFF_SIZE = 128
ENQ = '\x05'


class TPG336(TCPInterface):
    """Interface class for connecting to the Pfeiffer TPG366 maxigauge
    controller.


    Parameters
    ----------
    ip_address : str
        IP address of the device.
    port : int
        Associated port for TCP communication. Default is 8000.
    timeout : float
        Duration in seconds that operations wait before giving up. Default is
        10 seconds.

    Attributes
    ----------
    comm : socket.socket
        Socket object that forms the connection to the compressor.

    """

    def __init__(self, ip_address, port=8000, timeout=10):
        # Setup the TCP Interface
        super().__init__(ip_address, port, timeout)

    def channel_power(self):
        """
        Function to check the power status of all channels.

        Args:
            None

        Returns:
            List of channel states.

        """
        msg = 'SEN\r\n'
        self.send(msg.encode())
        self.recv(bufsize=BUFF_SIZE).decode()
        self.send(ENQ.encode())
        read_str = self.recv(bufsize=BUFF_SIZE).decode()
        power_str = read_str.split('\r')
        power_states = np.array(power_str[0].split(','), dtype=int)
        if any(chan == 1 for chan in power_states):
            channel_states = [index + 1 for index, state in enumerate(power_states) if state == 1]
            self.log.debug("The following channels are off: {}".format(channel_states))
        return channel_states

    def read_pressure(self, ch_no):
        """
        Function to measure the pressure of one given channel
        ch_no is the chanel to be measured (e.g. 1-6)
        returns the measured pressure as a float

        Args:
            ch_no: The channel to be measured (1-6)

        Returns:
            pressure as a float
        """
        msg = 'PR%d\r\n' % ch_no
        self.send(msg.encode())
        self.recv(bufsize=BUFF_SIZE).decode()
        self.send(ENQ.encode())
        read_str = self.recv(bufsize=BUFF_SIZE).decode()
        pressure_str = read_str.split(',')[-1].split('\r')[0]
        pressure = float(pressure_str)
        return pressure

    def read_pressure_all(self):
        """measure the pressure of all channel
        Return an array of 6 pressure values as a float array

        Args:
            None

        Returns:
            6 element array corresponding to each channels
            pressure reading, as floats
        """
        msg = 'PRX\r\n'
        self.send(msg.encode())
        # Could use this to catch exemptions, for troubleshooting
        self.recv(bufsize=BUFF_SIZE).decode()
        self.send(ENQ.encode())
        read_str = self.recv(bufsize=BUFF_SIZE).decode()
        pressure_str = read_str.split('\r')[0]
        gauge_states = pressure_str.split(',')[::2]
        gauge_states = np.array(gauge_states, dtype=int)
        pressures = pressure_str.split(',')[1::2]
        pressures = [float(p) for p in pressures]
        if any(state != 0 for state in gauge_states):
            index = np.where(gauge_states != 0)
            for j in index[0]:
                pressures[j] = 0.
        return pressures
