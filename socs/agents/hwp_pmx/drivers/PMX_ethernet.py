import socket
import time

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
        self.ip = ip
        self.port = port
        self.wait_time = 0.01
        self.buffer_size = 128
        self.conn = self._establish_connection(self.ip, int(self.port))

    def _establish_connection(self, ip, port, timeout=2):
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        attempts = 3
        for attempt in range(attempts):
            try:
                conn.connect((ip, port))
                break
            except (ConnectionRefusedError, OSError):
                print(f"Failed to connect to device at {ip}:{port}")
        else:
            raise RuntimeError('Could not connect to PMX.')
        return conn

    def close(self):
        self.conn.close()

    def send_message(self, msg, read=True):
        for attempt in range(2):
            try:
                self.conn.sendall(msg)
                time.sleep(0.5)
                if read:
                    data = self.conn.recv(self.buffer_size).strip().decode('utf-8')
                    return data
                return
            except (socket.timeout, OSError):
                print("Caught timeout waiting for responce from PMX. Trying again...")
                time.sleep(1)
                if attempt == 1:
                    print("Resetting connection")
                    self.conn.close()
                    self.conn = self._establish_connection(self.ip, int(self.port))
                    return self.send_message(msg, read=read)

    def wait(self):
        time.sleep(self.wait_time)

    def check_output(self):
        """ Return the output status """
        val = int(self.send_message(b'output?\n'))
        msg = "Measured output state = "
        states = {0: 'OFF', 1: 'ON'}
        if val in states:
            msg += states[val]
        else:
            msg += 'Fail'
        return msg, val

    def check_error(self):
        """ Check oldest error from error queues. Error queues store up to 255 errors """
        val = self.send_message(b':system:error?\n')
        code, msg = val.split(',')
        code = int(code)
        msg = msg[1:-2]
        return msg, code

    def clear_alarm(self):
        """ Clear alarm """
        self.send_message(b'output:protection:clear\n', read=False)

    def turn_on(self):
        """ Turn the PMX on """
        self.send_message(b'output 1\n', read=False)
        self.wait()
        return self.check_output()

    def turn_off(self):
        """ Turn the PMX off """
        self.send_message(b'output 0\n', read=False)
        self.wait()
        return self.check_output()

    def check_current(self):
        """ Check the current setting """
        val = float(self.send_message(b'curr?\n'))
        msg = "Current setting = {:.3f} A".format(val)
        return msg, val

    def check_voltage(self):
        """ Check the voltage setting """
        val = float(self.send_message(b'volt?\n'))
        msg = "Voltage setting = {:.3f} V".format(val)
        return msg, val

    def meas_current(self):
        """ Measure the current """
        val = float(self.send_message(b'meas:curr?\n'))
        msg = "Measured current = {:.3f} A".format(val)
        return msg, val

    def meas_voltage(self):
        """ Measure the voltage """
        val = float(self.send_message(b'meas:volt?\n'))
        msg = "Measured voltage = {:.3f} V".format(val)
        return msg, val

    def set_current(self, curr):
        """ Set the current """
        self.send_message(b'curr %a\n' % curr, read=False)
        self.wait()
        return self.check_current()

    def set_voltage(self, vol):
        """ Set the voltage """
        self.send_message(b'volt %a\n' % vol, read=False)
        self.wait()
        return self.check_voltage()

    def check_source(self):
        """ Check the source of PMX """
        val = self.send_message(b'volt:ext:sour?\n')
        msg = "Source: " + val
        return msg, val

    def use_external_voltage(self):
        """ Set PMX to use external voltage """
        self.send_message(b'volt:ext:sour volt\n', read=False)
        self.wait()
        return self.check_source()

    def ign_external_voltage(self):
        """ Set PMX to ignore external voltage """
        self.send_message(b'volt:ext:sour none\n', read=False)
        self.wait()
        return self.check_source()

    def check_current_limit(self):
        """ Check the PMX current protection limit """
        val = float(self.send_message(b'curr:prot?\n'))
        msg = "Current protection limit = {:.3f} A".format(val)
        return msg, val

    def check_voltage_limit(self):
        """ Check the PMX voltage protection limit """
        val = float(self.send_message(b'volt:prot?\n'))
        msg = "Voltage protection limit = {:.3f} V".format(val)
        return msg, val

    def set_current_limit(self, curr_lim):
        """ Set the PMX current protection limit """
        self.send_message(b'curr:prot %a\n' % curr_lim, read=False)
        self.wait()
        return self.check_current_limit()

    def set_voltage_limit(self, vol_lim):
        """ Set the PMX voltage protection limit """
        self.send_message(b'volt:prot %a\n' % vol_lim, read=False)
        self.wait()
        return self.check_voltage_limit()

    def check_prot(self):
        """ Check the protection status
        Return:
            val (int): protection status code
        """
        val = int(self.send_message(b'stat:ques?\n'))
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
