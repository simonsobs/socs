import errno
import select
import socket


class GripperClient(object):
    def __init__(self, ip, send_port, recv_port):
        self.ip = ip
        self.send_port = send_port
        self.recv_port = recv_port
        self.data = b''

        self._s_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s_send.setblocking(False)

        self._s_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s_recv.setblocking(False)

        self._s_recv.bind(('', self.recv_port))

    def POWER(self, state):
        if not isinstance(state, bool):
            return False

        if state:
            return self.send_command('ON')
        else:
            return self.send_command('OFF')

    def HOME(self):
        return self.send_command('HOME')

    def MOVE(self, mode, actuator, distance):
        if not isinstance(mode, str):
            return False
        elif mode.upper() not in ['POS', 'PUSH']:
            return False

        if actuator not in [1, 2, 3]:
            return False

        if type(distance) not in [float, int]:
            return False

        return self.send_command('MOVE ' + mode + ' ' + str(actuator) + ' ' + str(distance))

    def BRAKE(self, state, actuator=0):
        if not isinstance(state, bool):
            return False

        if actuator is 0:
            if state:
                return self.send_command('BRAKE ON')
            else:
                return self.send_command('BRAKE OFF')
        else:
            if actuator not in [1, 2, 3]:
                return False

            if state:
                return self.send_command('BRAKE ON ' + str(actuator))
            else:
                return self.send_command('BRAKE OFF ' + str(actuator))

    def EMG(self, state, actuator=0):
        if not isinstance(state, bool):
            return False

        if actuator is 0:
            if state:
                return self.send_command('EMG ON')
            else:
                return self.send_command('EMG OFF')
        else:
            if actuator not in [1, 2, 3]:
                return False

            if state:
                return self.send_command('EMG ON ' + str(actuator))
            else:
                return self.send_command('EMG OFF ' + str(actuator))

    def ALARM(self):
        return self.send_command('ALARM')

    def RESET(self):
        return self.send_command('RESET')

    def INP(self):
        return self.send_command('INP')

    def ACT(self, actuator):
        if actuator not in [1, 2, 3]:
            return False

        return self.send_command('ACT ' + str(actuator))

    def send_command(self, command):
        _ = self.listen()
        self.send_data(command)
        return self.listen(timeout=10)

    def send_data(self, data):
        if isinstance(data, str):
            self._s_send.sendto(bytes(data, 'utf-8'), (self.ip, self.send_port))
        elif isinstance(data, bytes):
            self._s_send.sendto(data, (self.ip, self.send_port))

    def listen(self, timeout=0.01):
        try:
            ready = select.select([self._s_recv], [], [], timeout)
            if ready[0]:
                self.data = self._s_recv.recv(1024)
        except socket.error as err:
            if err.errno != errno.EAGAIN:
                raise
            else:
                pass

        if len(self.data) > 0:
            return_data = self.data
            self.data = b''
            return return_data
        else:
            return b''

    def __exit__(self):
        self._s_send.close()
        self._s_recv.close()
