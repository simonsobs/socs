import time
from socket import AF_INET, SOCK_STREAM, socket

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


class PMX:
    """The PMX object for communicating with the Kikusui PMX power supplies.
    Args:
        tcp_ip (str): TCP IP address
        tcp_port (int): TCP port
    """

    def __init__(self, ip, port):
        self.sock = socket(AF_INET, SOCK_STREAM)
        self.sock.connect((ip, port))
        self.sock.settimeout(5)

        self.wait_time = 0.01
        self.buffer_size = 128

    def close(self):
        self.sock.close()

    def read(self):
        return self.sock.recv(self.buffer_size).decode('utf-8')

    def wait(self):
        time.sleep(self.wait_time)

    def check_output(self):
        """ Return the output status """
        self.sock.sendall(b'output?\n')
        val = int(self.read())
        msg = "Measured output state = "
        states = {0: 'OFF', 1: 'ON'}
        if val in states:
            msg += states[val]
        else:
            msg += 'Fail'
        return msg, val

    def check_error(self):
        """ Check oldest error from error queues. Error queues store up to 255 errors """
        self.sock.sendall(b':system:error?\n')
        val = self.read()
        code, msg = val.split(',')
        code = int(code)
        msg = msg[1:-2]
        return msg, code

    def clear_alarm(self):
        """ Clear alarm """
        self.sock.sendall(b'output:protection:clear\n')

    def turn_on(self):
        """ Turn the PMX on """
        self.sock.sendall(b'output 1\n')
        self.wait()
        return self.check_output()

    def turn_off(self):
        """ Turn the PMX off """
        self.sock.sendall(b'output 0\n')
        self.wait()
        return self.check_output()

    def check_current(self):
        """ Check the current setting """
        self.sock.sendall(b'curr?\n')
        val = float(self.read())
        msg = "Current setting = {:.3f} A".format(val)
        return msg, val

    def check_voltage(self):
        """ Check the voltage setting """
        self.sock.sendall(b'volt?\n')
        val = float(self.read())
        msg = "Voltage setting = {:.3f} V".format(val)
        return msg, val

    def meas_current(self):
        """ Measure the current """
        self.sock.sendall(b'meas:curr?\n')
        val = float(self.read())
        msg = "Measured current = {:.3f} A".format(val)
        return msg, val

    def meas_voltage(self):
        """ Measure the voltage """
        self.sock.sendall(b'meas:volt?\n')
        val = float(self.read())
        msg = "Measured voltage = {:.3f} V".format(val)
        return msg, val

    def set_current(self, curr):
        """ Set the current """
        self.sock.sendall(b'curr %a\n' % curr)
        self.wait()
        return self.check_current()

    def set_voltage(self, vol):
        """ Set the voltage """
        self.sock.sendall(b'volt %a\n' % vol)
        self.wait()
        return self.check_voltage()

    def check_source(self):
        """ Check the source of PMX """
        self.sock.sendall(b'volt:ext:sour?\n')
        val = self.read()
        msg = "Source: " + val
        return msg

    def use_external_voltage(self):
        """ Set PMX to use external voltage """
        self.sock.sendall(b'volt:ext:sour volt\n')
        self.wait()
        return self.check_source()

    def ign_external_voltage(self):
        """ Set PMX to ignore external voltage """
        self.sock.sendall(b'volt:ext:sour none\n')
        self.wait()
        return self.check_source()

    def set_current_limit(self, curr_lim):
        """ Set the PMX current limit """
        self.sock.sendall(b'curr:prot %a\n' % curr_lim)
        self.wait()
        self.sock.sendall(b'curr:prot?\n')
        val = float(self.read())
        msg = "Current Limit: {:.3f} A".format(val)
        return msg

    def set_voltage_limit(self, vol_lim):
        """ Set the PMX voltage limit """
        self.sock.sendall(b'volt:prot %a\n' % vol_lim)
        self.wait()
        self.sock.sendall(b'volt:prot?\n')
        val = float(self.read())
        msg = "Voltage Limit: {:.3f} V".format(val)
        return msg

    def check_prot(self):
        """ Check the protection status
        Return:
            val (int): protection status code
        """
        self.sock.sendall(b'stat:ques?\n')
        val = int(self.read())
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
