import time
import socket


class EthernetInterface:
    def __init__(self, ip_address, port_number, **kwargs):
        self.ip_address = ip_address
        self.port_number = port_number
        self.sock = None
        self.conn_socket()
        super().__init__(**kwargs)

    def conn_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip_address, self.port_number))
        self.sock.settimeout(5)

    def write(self, msg):
        message = msg + '\n'
        self.sock.sendall(message.encode())
        time.sleep(0.1)  # Don't send messages too quickly

    def read(self):
        return self.sock.recv(128).decode().strip()

    def version(self):
        self.write('++ver')
        return self.read()

    def identify(self):
        self.write('*idn?')
        return self.read()
