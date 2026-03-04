import time

from socs.tcp import TCPInterface

WAIT_TIME = 0.01
BUFFSIZE = 128

protection_status_key = [
    'Over voltage',
    'Over current',
    'AC power failure or power interuption',
    '',
    'Over temperature',
    '',
    'IOC communication error',
    '',
]


class PMX(TCPInterface):
    """The PMX object for communicating with the Kikusui PMX power supplies.

    Args:
        ip_address (str): IP address of the device.
        port (int): Associated port for TCP communication.
        timeout (float): Duration in seconds that operations wait before giving
            up.

    """

    def __init__(self, ip_address, port=5025, timeout=10):
        # Setup the TCP Interface
        super().__init__(ip_address, port, timeout)

    def close(self):
        self.comm.close()

    def send_message(self, msg, read=True):
        if not msg[-1] == '\n':
            msg += '\n'
        self.send(msg.encode())
        time.sleep(0.5)
        if read:
            data = self.recv(BUFFSIZE).strip().decode('utf-8')
            return data

    def _wait(self):
        time.sleep(WAIT_TIME)

    def check_output(self):
        """ Return the output status """
        val = int(self.send_message('output?'))
        msg = "Measured output state = "
        states = {0: 'OFF', 1: 'ON'}
        if val in states:
            msg += states[val]
        else:
            msg += 'Fail'
        return msg, val

    def check_error(self):
        """ Check oldest error from error queues. Error queues store up to 255 errors """
        val = self.send_message(':system:error?')
        code, msg = val.split(',')
        code = int(code)
        msg = msg[1:-2]
        return msg, code

    def clear_alarm(self):
        """ Clear alarm """
        self.send_message('output:protection:clear', read=False)

    def turn_on(self):
        """ Turn the PMX on """
        self.send_message('output 1', read=False)
        self._wait()
        return self.check_output()

    def turn_off(self):
        """ Turn the PMX off """
        self.send_message('output 0', read=False)
        self._wait()
        return self.check_output()

    def check_current(self):
        """ Check the current setting """
        val = float(self.send_message('curr?'))
        msg = "Current setting = {:.3f} A".format(val)
        return msg, val

    def check_voltage(self):
        """ Check the voltage setting """
        val = float(self.send_message('volt?'))
        msg = "Voltage setting = {:.3f} V".format(val)
        return msg, val

    def meas_current(self):
        """ Measure the current """
        val = float(self.send_message('meas:curr?'))
        msg = "Measured current = {:.3f} A".format(val)
        return msg, val

    def meas_voltage(self):
        """ Measure the voltage """
        val = float(self.send_message('meas:volt?'))
        msg = "Measured voltage = {:.3f} V".format(val)
        return msg, val

    def set_current(self, curr):
        """ Set the current """
        self.send_message('curr %a' % curr, read=False)
        self._wait()
        return self.check_current()

    def set_voltage(self, vol):
        """ Set the voltage """
        self.send_message('volt %a' % vol, read=False)
        self._wait()
        return self.check_voltage()

    def check_source(self):
        """ Check the source of PMX """
        val = self.send_message('volt:ext:sour?')
        msg = "Source: " + val
        return msg, val

    def use_external_voltage(self):
        """ Set PMX to use external voltage """
        self.send_message('volt:ext:sour volt', read=False)
        self._wait()
        return self.check_source()

    def ign_external_voltage(self):
        """ Set PMX to ignore external voltage """
        self.send_message('volt:ext:sour none', read=False)
        self._wait()
        return self.check_source()

    def check_current_limit(self):
        """ Check the PMX current protection limit """
        val = float(self.send_message('curr:prot?'))
        msg = "Current protection limit = {:.3f} A".format(val)
        return msg, val

    def check_voltage_limit(self):
        """ Check the PMX voltage protection limit """
        val = float(self.send_message('volt:prot?'))
        msg = "Voltage protection limit = {:.3f} V".format(val)
        return msg, val

    def set_current_limit(self, curr_lim):
        """ Set the PMX current protection limit """
        self.send_message('curr:prot %a' % curr_lim, read=False)
        self._wait()
        return self.check_current_limit()

    def set_voltage_limit(self, vol_lim):
        """ Set the PMX voltage protection limit """
        self.send_message('volt:prot %a' % vol_lim, read=False)
        self._wait()
        return self.check_voltage_limit()

    def check_prot(self):
        """ Check the protection status
        Return:
            val (int): protection status code
        """
        val = int(self.send_message('stat:ques?'))
        return val

    def get_prot_msg(self, val):
        """ Get the protection status message
        Args:
            val (int): protection status code
        Return:
            msg (str): protection status message
        """
        msg = []
        for i in range(8):
            if (val >> i & 1):
                msg.append(protection_status_key[i])
        msg = ', '.join(msg)
        return msg
