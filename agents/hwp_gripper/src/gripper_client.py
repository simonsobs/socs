import select
import socket
import sys
import time


class GripperClient(object):
    def __init__(self, mcu_ip, port):
        self.ip = mcu_ip
        self.port = port

        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s.setblocking(0)

    def send_data(self, data):
        self._s.sendto(bytes(data, 'utf-8'), (self.ip, self.port))
        # self._s.recv(1024).decode(encoding = 'UTF-8')

    def __exit__(self):
        self._s.close()
