# 4/2009 BAS
#  read() replicates behavior of pyserial
#  readexactly() added, which is probably more useful
#  readbuf() dumps current buffer contents
#  readpacket() has old broken behavior of read() - lowest level / fastest


# Class to speak with the moxa serial / Ethernet converter
# Set up the moxa box ports according to the specifications of the device hooked into each serial port.

# A typical sequence of messages for dealing with a device
# Create the socket once:
#  moxa = moxa_serial.Serial_TCPServer(('IP',port),timeout=1.0)

# Then do this sequence, complicated in some way by an individual device's hand shaking needs.  I write a "cmd" methods that handle the proper sequence with checksums etc.

#  moxa.flushInput():  Before I ask for new info from a device, I flush my receive buffer to make sure I don't get any garbage in front.

#  moxa.write(msg):  Sends message to the moxa box.  Most devices need a message terminator like '\r\n'.

#  moxa.readexactly(n):  Tries to read n bytes within the timeout.  If it doesn't get n bytes, it returns nothing!


# Other methods:

#  moxa.readbuf(n):  Returns whatever is currently in the buf.

# moxa.readpacket(n):  Like moxa.read(), but may not return everything if the moxa box flushes too soon

#  moxa.read(n):  Like moxa.readexactly(), but returns whatever is in the buffer if it can't fill up.
#   This replicates the behavior of the read method in pyserial.
#   I feel that moxa.readexactly has better behavior for most applications though.


#  moxa.timeout = <newtimeout> to set timeout.  Only use timeout mode with timeout >0.0.


# Most devices require a certain delay between commands.
# Multithreading:  Wrap your delays in mutexes
# See ls218.py for a simple example
# See des232.py for a complicated example

import time
import socket

MOXA_DEFAULT_TIMEOUT = 1.0

# Socket modes:
# Nonblocking
#  s.setblocking(0) means s.settimeout(0)
#  Read returns as much data as possible, does not fail
#  Doesn't work for me on windows.  Don't use.
# Timeout
#  s.settimeout(n)
#  Waits until buffer has enough data, then returns
#  Throws exception (caught by read) if not enough data is ready after n second.
#  Read returns '' on fail
# Blocking
#  s.setblocking(1) or s.settimeout(None)
#  Waits forever until buffer has enough data, then returns
#  This is the default mode for sockets
#  Check socket.getdefaulttimeout() to see what mode sockets are created in

# pyserial style wrapper over IA 5250 TCP Server mode
class Serial_TCPServer(object):

	def __init__(self,port,timeout=MOXA_DEFAULT_TIMEOUT):
		# port is a tuple of form (IP addr, TCP port)
		self.port = port

		self.sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
		self.sock.setblocking(0)
		self.settimeout(timeout)
		self.sock.connect(self.port)

	# Reads exactly n bytes, waiting up to timeout.
	def readexactly(self,n):
		t0 = time.time()
		msg = ""
		timeout = self.gettimeout()
		while len(msg) < n:
			newtimeout = timeout-(time.time()-t0)
			if newtimeout <= 0.0: break
			self.settimeout(newtimeout)
			try:
				msg = self.sock.recv(n,socket.MSG_PEEK)
			except:
				pass
		# Flush the message out if you got everything
		if len(msg) == n: msg = self.sock.recv(n)
		# Otherwise tell nothing and leave the data in the buffer
		else: msg = ''
		self.settimeout(timeout)
		return msg


	# Reads whatever is in the buffer right now, but is O(N) in buffer size.
	def readbuf_slow(self,n):
		msg = ''
		self.sock.setblocking(0)
		try:
			for i in range(n):
				msg += self.sock.recv(1)
		except: pass
		self.sock.setblocking(1)	# belt and suspenders
		self.settimeout(self.__timeout)
		return msg

	# Log recode of readbuf.  Usable for large buffers.
	def readbuf(self,n):
		if n == 0: return ''
		try:
			msg = self.sock.recv(n)
		except: msg = ''
		n2 = min(n-len(msg),n/2)
		return msg + self.readbuf(n2)


	# Will probably read whatever arrives in the buffer, up to n or the timeout
	# Use read for certainty
	def readpacket(self,n):
		try:
			msg = self.sock.recv(n)
		except:
			msg = ''
		return msg

	# Will read whatever arrives in the buffer, up to n or the timeout
	def read(self,n):
		msg = self.readexactly(n)
		n2 = n-len(msg)
		if n2 > 0: msg += self.readbuf(n2)
		return msg

	def readline(self,term='\n'):
		msg = ''
		while True:
			c = self.readexactly(1)
			if c == term or c == '':
				return msg
			msg += c.decode()

	def readall(self):
		msg = ""
		while 1:
			c = self.readexactly(1)
			if c == '\r': return msg
			if c == '': return False
			msg += c
		return msg

	def write(self,str):
		self.sock.send(str)

	def writeread(self,str):
		self.flushInput()
		self.write(str)
		return self.readall()

	# Erases the input buffer at this moment
	def flushInput(self):
		self.sock.setblocking(0)
		try:
			while len(self.sock.recv(1))>0: pass
		except: pass
		self.sock.setblocking(1)
		self.sock.settimeout(self.__timeout)

	# Sets the socket in timeout mode
	def settimeout(self,timeout):
		assert timeout > 0.0
		self.__timeout = timeout
		self.sock.settimeout(timeout)
	# We don't query the socket's timeout or check that they're still correct
	# Since self.sock e is public this could be the wrong timeout!
	def gettimeout(self):
		return self.__timeout

	timeout = property(gettimeout,settimeout)

def test1():
	x = Serial_TCPServer(('google.com',80),timeout=1.15)
	x.write('GET /\n')
	print(x.readexactly(1000))

def test2():
	x = Serial_TCPServer(('google.com',80),timeout=0.15)
	x.write('GET /\n')
	print(x.read(10000))
