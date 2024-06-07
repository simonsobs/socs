import socket
import time


class PrologixInterface:
    def __init__(self, ip_address, gpibAddr, **kwargs):
        self.ip_address = ip_address
        self.gpibAddr = gpibAddr
        self.isPrologix = True
        self.sock = None
        self.port = 1234
        if('port' in kwargs.keys()):
            self.isPrologix = False
            self.port = kwargs['port']
            del kwargs['port']
            self.conn_socket()
        else:
            self.conn_socket()
            self.configure()
        super().__init__(**kwargs)

    def conn_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip_address, self.port))
        self.sock.settimeout(5)

    def configure(self):
        if(self.isPrologix):
            self.write('++mode 1')
            self.write('++auto 1')
            self.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        message = msg + '\n'
        self.sock.sendall(message.encode())
        time.sleep(0.1)  # Don't send messages too quickly

    def read(self):
        return self.sock.recv(128).decode().strip()

    def version(self):
        if(self.isPrologix):
            self.write('++ver')
            return self.read()
        else:
            return 'not-prologix'

    def identify(self):
        self.write('*idn?')
        return self.read()
