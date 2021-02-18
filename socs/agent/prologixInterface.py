import socket

DEFAULT_ESCAPE = 'xYzZyX'


class PrologixInterface:
    def __init__(self, ip, escape_string=DEFAULT_ESCAPE):
        self.ip = ip
        self.escape_string = escape_string
        self.sock = None
        self.connSocket()
        self.configure()

    def connSocket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip, 1234))
        self.sock.settimeout(5)

    def configure(self):
        self.write('++mode 1\n')
        self.write('++auto 1\n')

    def write(self, msg):
        message = msg + '\n'
        self.sock.send(message.encode())

    def read(self):
        return self.sock.recv(128).decode().rstrip('\n').rstrip('\r')

    def identify(self):
        self.write('++ver')
        return self.read()


class GpibInterface(PrologixInterface):
    def __init__(self, ip_address, gpibAddr):
        super().__init__(ip_address)
        self.gpibAddr = gpibAddr

    def write(self, msg):
        self.sock.write('++addr ' + str(self.gpibAddr))
        super().write(msg)

    def identify(self):
        self.write('*idn?')
        return self.read()
