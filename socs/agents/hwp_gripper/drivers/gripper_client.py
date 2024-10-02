import pickle as pkl
import socket
import time


class GripperClient(object):
    def __init__(self, ip, port):
        self.ip = ip
        self.port = port
        self.control_socket = self._init_connection(self.ip, self.port)
        self.data = b''

    def _init_connection(self, ip, port):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip, port))
        return s

    def power(self, state):
        if not isinstance(state, bool):
            return False

        if state:
            return self.send_command('ON')
        else:
            return self.send_command('OFF')

    def home(self):
        return self.send_command('HOME')

    def move(self, mode, actuator, distance):
        if not isinstance(mode, str):
            return False
        elif mode.upper() not in ['POS', 'PUSH']:
            return False

        if actuator not in [1, 2, 3]:
            return False

        if type(distance) not in [float, int]:
            return False

        return self.send_command('MOVE ' + mode + ' ' + str(actuator) + ' ' + str(distance))

    def brake(self, state, actuator=0):
        if not isinstance(state, bool):
            return False

        if actuator == 0:
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

    def emg(self, state, actuator=0):
        if not isinstance(state, bool):
            return False

        if actuator == 0:
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

    def alarm(self):
        return self.send_command('ALARM')

    def alarm_group(self):
        return self.send_command('ALARM_GROUP')

    def reset(self):
        return self.send_command('RESET')

    def inp(self):
        return self.send_command('INP')

    def act(self, actuator):
        if actuator not in [1, 2, 3]:
            return False

        return self.send_command('ACT ' + str(actuator))

    def is_cold(self, value):
        if value:
            return self.send_command('IS_COLD 1')
        else:
            return self.send_command('IS_COLD 0')

    def force(self, value):
        if value:
            return self.send_command('FORCE 1')
        else:
            return self.send_command('FORCE 0')

    def get_state(self):
        return self.send_command('GET_STATE')

    def send_command(self, command):
        if isinstance(command, str):
            self.control_socket.sendall(bytes(command, 'utf-8'))
        elif isinstance(command, bytes):
            self.control_socket.sendall(command)

        return pkl.loads(self.control_socket.recv(4096))

    def restart(self):
        log = []
        try:
            self.close()
            log.append('Previous connection closed')
        except BaseException:
            log.append('Previous connection already closed')

        _restart_socket = self._init_connection(self.ip, 5656)
        _restart_socket.sendall(('reset\n').encode())
        time.sleep(0.5)

        resp = _restart_socket.recv(4096).decode().strip()
        log.append(f'Restart command response: {resp}')
        result = True if resp == 'Success' else False
        _restart_socket.close()
        time.sleep(10)

        self.control_socket = self._init_connection(self.ip, self.port)
        log.append('Control socket reconnected')
        return {'result': result, 'log': log}

    def close(self):
        """Close socket connection"""
        self.control_socket.close()
