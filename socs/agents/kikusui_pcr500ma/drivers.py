#!/usr/bin/env python3
'''PCR500MA driver using SCPI-RAW protocol'''
import sys
from enum import Enum

from socs.tcp import TCPInterface

PORT = 5025
TIMEOUT_DEFAULT = 3
BUFFSIZE = 4096

# software limits
VOLT_ULIM_SOFT = 51


class PCRException(Exception):
    pass


class PCRCoupling(Enum):
    AC = 'AC'
    DC = 'DC'
    ACDC = 'ACDC'


class PCR500MA(TCPInterface):
    """PCR500MA driver

    Parameters
    ----------
    ip_addr : str
        IP address of the device
    port : int
        Port number
    timeout : float
        Timeout count in seconds
    """

    def __init__(self, ip_addr, port=PORT, timeout=TIMEOUT_DEFAULT):
        super().__init__(ip_addr, port, timeout)

    def _send(self, message):
        """Send message to PCR500MA

        Parameters
        ----------
        message : str
            Message string to be sent to PCR500MA
        """
        if not message[-1] == '\n':
            message += '\n'

        self.send(message.encode())

    def _recv(self):
        """Receive message from PCR500MA"""
        msg_byte = self.recv(BUFFSIZE)

        return msg_byte.decode()

    def _query(self, message):
        self._send(message)
        return self._recv().strip()

    def get_idn(self):
        """Get identification string"""
        return self._query('*IDN?')

    def reset(self):
        """Reset PCR500MA device"""
        return self._send('*RST')

    def set_output(self, output):
        """Set output status

        Parameters
        ----------
        output : bool
            True : output on
            False : output off
        """
        message = f'OUTP {"1" if output else "0"}'
        self._send(message)

    def turn_on(self):
        """Turn on"""
        self.set_output(True)

    def turn_off(self):
        """Trun off"""
        self.set_output(False)

    def get_output(self):
        """Get output status

        Returns
        -------
        status : bool
            True : output on
            False : output off
        """
        message = self._query('OUTP?')

        if message == '1':
            return True
        elif message == '0':
            return False
        else:
            raise PCRException(f'Failed to get output status: {message}')

    def set_coupling(self, pcr_coupling):
        """Set output coupling

        Parameters
        ----------
        pcr_coupling : PCRCoupling
            PCR coupling
        """
        message = f'OUTP:COUP {pcr_coupling.value}'
        self._send(message)

    def get_coupling(self):
        """Get output coupling

        Returns
        -------
        pcr_coupling : PCRCoupling
            PCR coupling
        """
        message = self._query('OUTP:COUP?')

        return PCRCoupling(message)

    def clear_alarm(self):
        """Clear alarm"""
        self._send('OUTP:PROT:CLE')

    def set_current_limit_ac(self, current_amp):
        """Set AC current upper limit

        Parameters
        ----------
        current_amp : float
            AC currrent upper limit in Ampere.
        """
        message = f'CURR {current_amp}'
        self._send(message)

    def get_current_limit_ac(self):
        """Get AC current upper limit

        Returns
        -------
        current_amp : float
            AC current upper limit in Ampere.
        """
        message = self._query('CURR?')
        return float(message)

    def set_current_limit_dc(self, current_amp):
        """Set DC current upper limit

        Parameters
        ----------
        current_amp : float
            DC currrent upper limit in Ampere.
        """
        message = f'CURR:OFFS {current_amp}'
        self._send(message)

    def get_current_limit_dc(self):
        """Get DC current upper limit

        Returns
        -------
        current_amp : float
            DC current upper limit in Ampere.
        """
        message = self._query('CURR:OFFS?')
        return float(message)

    def set_frequency(self, freq, freq_llim=None, freq_ulim=None):
        """Set AC frequency.

        Parameters
        ----------
        freq : float
            Frequency in Hz.
        freq_llim : float
            Frequency lower limit in Hz.
        freq_ulim : float
            Frequency upper limit in Hz.
        """

        assert 40 <= freq <= 500, 'Frequency should be within [40, 500] Hz'

        if (freq_llim is None) and (freq_ulim is None):
            message = f'FREQ {freq}'
        elif (freq_llim is None) or (freq_ulim is None):
            raise PCRException('Lower limit and upper limit should be given simultaneously.')
        else:
            assert freq_llim <= freq <= freq_ulim, 'Target frequency is not in the given range'
            message = f'FREQ {freq},{freq_llim},{freq_ulim}'

        self._send(message)

    def get_frequency(self):
        """Get AC frequency

        Returns
        -------
        freq : float
            Frequency in Hz
        """

        message = self._query('FREQ?')
        return float(message)

    def set_volt_ac(self, volt, volt_llim=None, volt_ulim=None):
        """Set AC voltage

        Parameters
        ----------
        volt : float
            AC voltage in V.
        volt_llim : float
            AC voltage lower limit in V.
        volt_ulim : float
            AC voltage upper limit in V.
        """
        assert 0 <= volt <= VOLT_ULIM_SOFT, f'Voltage should be within [0, {VOLT_ULIM_SOFT}] V'

        if (volt_llim is None) and (volt_ulim is None):
            message = f'VOLT {volt}'
        elif (volt_llim is None) or (volt_ulim is None):
            raise PCRException('Lower limit and upper limit should be given simultaneously.')
        else:
            assert volt_llim <= volt <= volt_ulim, 'Target voltage is not in the given range'
            message = f'VOLT {volt},{volt_llim},{volt_ulim}'

        self._send(message)

    def get_volt_ac(self):
        """Get AC voltage setting

        Returns
        -------
        volt : float
            AC voltage setting in V.
        """

        message = self._query('VOLT?')
        return float(message)

    def meas_volt_ac(self):
        """Measure AC voltage

        Returns
        -------
        volt : float
            Measured AC voltage in V.
        """

        message = self._query('MEAS:VOLT:AC?')
        return float(message)

    def meas_current_ac(self):
        """Measure AC current

        Returns
        -------
        current : float
            Measured AC current in A.
        """

        message = self._query('MEAS:CURR:AC?')
        return float(message)

    def meas_power_ac(self):
        """Measure AC power

        Returns
        -------
        power : float
            Measured power in W.
        """
        message = self._query('MEAS:POW:AC?')
        return float(message)

    def meas_freq(self):
        """Measure frequency

        Returns
        -------
        freq : float
            Measured frequency in Hz.
        """
        message = self._query('MEAS:FREQ?')
        return float(message)


def main():
    """Main function"""
    inst = PCR500MA(sys.argv[1])
    print(inst.get_idn())
    print(inst.get_output())
    print(inst.get_coupling())
    print(inst.get_current_limit_ac())
    print(inst.get_current_limit_dc())
    print(inst.get_frequency())
    print(inst.get_volt_ac())
    print(inst.meas_volt_ac())
    print(inst.meas_current_ac())
    print(inst.meas_power_ac())
    print(inst.meas_freq())


if __name__ == '__main__':
    main()
