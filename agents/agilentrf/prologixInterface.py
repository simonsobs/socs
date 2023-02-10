import socket as socket

# ip = '10.10.10.165' # '192.168.1.3', '192.168.1.8'
#escapeString = 'xYzZyX'


class prologixInterface:

    def __init__(self, ip, gpibAddr):
        self.ip = ip
        self.gpibAddr = gpibAddr
        self.pro = None
        #self.escapeString = escapeString
        # self.connSocket()
        # self.configure()

    def connSocket(self):
        self.pro = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.pro.connect((self.ip, 1234))
        self.pro.settimeout(10000)

    def confGpib(self):
        self.pro.send(('++addr ' + str(self.gpibAddr) + '\n').encode())

    # def configure(self):
        #self.write('++mode 1\n')
        #self.write('++auto 1\n')
        ##self.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        self.confGpib()
        self.pro.send((msg + '\n').encode())

    # def writeGpib(self, msg):
        #self.write('++addr ' + str(self.gpibAddr))
        # self.write(msg)

    def read(self):
        return self.pro.recv(128).decode().rstrip('\n').rstrip('\r')

    def identify(self):
        self.write('++ver'.encode())
        return self.read()
