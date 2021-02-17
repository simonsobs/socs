import socket as socket

DEFAULT_IP = '192.168.1.3'
DEFAULT_ESCAPE = 'xYzZyX'


class prologixInterface:

    def __init__(self, ip=DEFAULT_IP, escapeString=DEFAULT_ESCAPE):
        self.ip = ip
        self.escapeString = escapeString
        #self.gpibAddr = gpibAddr
        self.connSocket()
        self.configure()

    def connSocket(self):
        self.pro = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.pro.connect((self.ip, 1234))
        self.pro.settimeout(5)

    def configure(self):
        self.write('++mode 1\n')
        self.write('++auto 1\n')
        #self.write('++addr ' + str(self.gpibAddr))

    def write(self, msg):
        message = msg + '\n'
        self.pro.send(message.encode())

#	def writeGpib(self, gpibAddr, msg):
#		self.write('++addr ' + str(gpibAddr))
#		self.write(msg)

    def read(self):
        return self.pro.recv(128).decode().rstrip('\n').rstrip('\r')

    def identify(self):
        self.write('++ver')
        return self.read()
