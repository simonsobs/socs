import socket
import os
import sys
import select
import errno

this_dir = os.path.dirname(__file__)
sys.path.append(this_dir)

import BBB as bb
import JXC831 as jx
import control as ct
import gripper as gp
import command_gripper as cg
import gripper_client as gc

class GripperServer(object):
    def __init__(self, host_ip, command_port, return_port):
        self.host_ip = host_ip
        self.command_port = command_port
        self.return_port = return_port

        self.client = gc.GripperClient(self.host_ip, self.return_port, self.command_port)
        self.data = b''

        self.BBB = bb.BBB()
        self.JXC = jx.JXC831(self.BBB)
        self.CTL = ct.Control(self.JXC)
        self.GPR = gp.Gripper(self.CTL)
        self.CMD = cg.Command(self.GPR)

    def process_command(self):
        while True:
            self.data = self.client.listen()

            if len(self.data) > 0:
                return_value = self.CMD.CMD(self.data.decode(encoding = 'UTF-8'))
                self.client.send_data(str(return_value))
                self.data = b''

server = GripperServer('10.10.10.50', 8041, 8042)
server.process_command()
