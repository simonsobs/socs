import socket


class PrologixInterface:
    def __init__(self, ip_address, gpibAddr, **kwargs):
        self.ip_address = ip_address
        self.gpibAddr = gpibAddr
        self.sock = None
        self.conn_socket()
        self.configure()
        super().__init__(**kwargs)

    def conn_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip_address, 1234))
        self.sock.settimeout(5)

    def configure(self):
        self.write('++mode 1\n')
        self.write('++auto 1\n')
        self.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        message = msg + '\n'
        self.sock.send(message.encode())

    def read(self):
        return self.sock.recv(128).decode().rstrip('\n').rstrip('\r')

    def version(self):
        self.write('++ver')
        return self.read()

    def identify(self):
        self.write('*idn?')
        return self.read()
