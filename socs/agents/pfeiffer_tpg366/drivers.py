# Original script by Zhilei Xu and Tanay Bhandarkar.

import numpy as np

from socs.tcp import TCPInterface

BUFF_SIZE = 4096
ENQ = '\x05'


class TPG366(TCPInterface):
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

        # On boot the TPG366 starts in 'continuous transmission' mode. This
        # sends a single 'ENQ', which stops transmission.
        try:
            self._send_enquiry()
            print('Startup ENQ response:', self.recv())
        except ConnectionError as e:
            print(f'Encountered error connecting to device: {e}')

    def _send_mnemonic(self, mnemonic):
        """Send a mnemonic.

        Parameters
        ----------
        mnemonic : str
            Unencoded mnemonic string, with terminating characters, i.e. 'PRX\r'.

        Returns
        -------
        Enocded response from the device. Typically an ACK, unless the device
        is in a strange state.

        """
        self.send(mnemonic.encode())
        resp = self.recv(bufsize=BUFF_SIZE)  # don't decode, might just be ACK
        return resp

    def _send_enquiry(self):
        self.send(ENQ.encode())

    def send_and_recv(self, message):
        """Send message and request transmission of queried data from device.

        The flow control for querying the TPG366 involves first sending a
        message (referred to in the TPG366 manual as a mnemonic) to set the
        measuring mode, receiving positive feedback from the device, then
        sending a request for transmission from the device, followed finally by
        receiving the measurement data.

        This method combines these four steps into one.

        Parameters
        ----------
        message : str
            Mnemonic command code message with parameters.

        Returns
        -------
        Decoded response from the device.

        """
        self._send_mnemonic(message)
        self._send_enquiry()
        read_str = self.recv(bufsize=BUFF_SIZE).decode()

        return read_str

    def channel_power(self):
        """
        Check the power state of all channels.

        Returns
        -------
        list
            List of channel states.

        """
        msg = 'SEN\r\n'
        read_str = self.send_and_recv(msg)
        power_str = read_str.split('\r')
        power_states = np.array(power_str[0].split(','), dtype=int)
        if any(chan == 1 for chan in power_states):
            channel_states = [index + 1 for index, state in enumerate(power_states) if state == 1]
        return channel_states

    def read_pressure(self, ch_no):
        """Measure the pressure of one given channel.

        Parameters
        ----------
        ch_no : int
            The channel to be measured (1-6).

        Returns
        -------
        float
            Channel pressure.

        """
        msg = 'PR%d\r\n' % ch_no
        read_str = self.send_and_recv(msg)
        pressure_str = read_str.split(',')[-1].split('\r')[0]
        pressure = float(pressure_str)
        return pressure

    def read_pressure_all(self):
        """Measure the pressure of all channels.

        Returns
        -------
        np.array
            Six element array corresponding to each channels pressure reading,
            as floats.

        """
        msg = 'PRX\r\n'
        read_str = self.send_and_recv(msg)
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
