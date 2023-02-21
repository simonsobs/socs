import errno
import os
import select
import socket
import sys

this_dir = os.path.dirname(__file__)
sys.path.append(this_dir)

import BBB as bb
import command_gripper as cg
import control as ct
import gripper as gp
import JXC831 as jx


class GripperServer(object):
    def __init__(self, port):
        self.port = port
        self.data = b''

        self.BBB = bb.BBB()
        self.JXC = jx.JXC831(self.BBB)
        self.CTL = ct.Control(self.JXC)
        self.GPR = gp.Gripper(self.CTL)
        self.CMD = cg.Command(self.GPR)

        self._s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._s.setblocking(False)

        self._s.bind(("", self.port))

    def listen(self):
        while True:
            try:
                ready = select.select([self._s], [], [], 0.01)
                if ready[0]:
                    self.data = self._s.recv(1024)
            except socket.error as err:
                if err.errno != errno.EAGAIN:
                    raise
                else:
                    pass

            if len(self.data) > 0:
                self.CMD.CMD(self.data.decode(encoding='UTF-8'))
                self.data = b''

    def __exit__(self):
        self._s.close()


server = GripperServer(8041)
server.listen()
