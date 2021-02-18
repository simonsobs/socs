import socket

DEFAULT_ESCAPE = 'xYzZyX'


class GpibInterface:
    def __init__(self, ip_address, gpibAddr):
        self.pro = PrologixInterface(ip=ip_address)
        self.gpibAddr = gpibAddr

    def connGpib(self):
        self.pro.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        self.connGpib()
        self.pro.write(msg)

    def read(self):
        return self.pro.read()

    def identify(self):
        self.write('*idn?')
        return self.read()


class PrologixInterface:
    def __init__(self, ip, escape_string=DEFAULT_ESCAPE):
        self.ip = ip
        self.escape_string = escape_string
        # self.gpibAddr = gpibAddr
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
        # self.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        message = msg + '\n'
        self.sock.send(message.encode())

    # def writeGpib(self, gpibAddr, msg):
    # 	self.write('++addr ' + str(gpibAddr))
    # 	self.write(msg)

    def read(self):
        return self.sock.recv(128).decode().rstrip('\n').rstrip('\r')

    def identify(self):
        self.write('++ver')
        return self.read()
