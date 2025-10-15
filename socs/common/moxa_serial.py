# 4/2009 BAS
#  read() replicates behavior of pyserial
#  readexactly() added, which is probably more useful
#  readbuf() dumps current buffer contents
#  readpacket() has old broken behavior of read() - lowest level / fastest

import socket
import time

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
    """Class to speak with the moxa serial / Ethernet converter.
    Set up the moxa box ports according to the specifications of the device
    hooked into each serial port.

    A typical sequence of messages for dealing with a device. Create the
    socket once::

        >>> moxa = moxa_serial.Serial_TCPServer(('IP',port),timeout=1.0)

    Then do this sequence, complicated in some way by an individual device's hand
    shaking needs::

        >>> moxa.flushInput()
        >>> moxa.write(msg)
        >>> moxa.readexactly(n)

    I write a "cmd" methods that handle the proper sequence with checksums etc.
    Most devices require a certain delay between commands, which is left to the
    user. If using multithreading, wrap your delays in mutexes.

    Args:
        port (tuple): (IP addr, TCP port)
        timeout (float): Timeout for reading from the moxa box
        encoded (bool): Encode/decode messages before/after sending/receiving if True.
                        Send messages unmodified if False. Defaults to True.

    """

    def __init__(self, port, timeout=MOXA_DEFAULT_TIMEOUT, encoded=True):
        self.port = port
        self.encoded = encoded

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setblocking(0)
        self.settimeout(timeout)
        self.sock.connect(self.port)

    def readexactly(self, n):
        """Tries to read exactly n bytes within the timeout.

        Args:
            n: Number of bytes to read.

        Returns:
            str: Returned message if n bytes were read. Empty string if
            ``len(message) != n``.

        """
        t0 = time.time()
        msg = ""
        timeout = self.gettimeout()
        while len(msg) < n:
            newtimeout = timeout - (time.time() - t0)
            if newtimeout <= 0.0:
                break
            self.settimeout(newtimeout)
            try:
                msg = self.sock.recv(n, socket.MSG_PEEK)
            except BaseException:
                pass
        # Flush the message out if you got everything
        if len(msg) == n:
            if self.encoded:
                msg = self.sock.recv(n).decode()
            else:
                msg = self.sock.recv(n)
        # Otherwise tell nothing and leave the data in the buffer
        else:
            msg = ''
        self.settimeout(timeout)
        return msg

    def readbuf_slow(self, n):
        """Reads whatever is in the buffer right now, but is O(N) in buffer
        size.

        Args:
            n: Number of bytes to read.

        """
        msg = ''
        self.sock.setblocking(0)
        try:
            for i in range(n):
                msg += self.sock.recv(1)
        except BaseException:
            pass
        self.sock.setblocking(1)  # belt and suspenders
        self.settimeout(self.__timeout)
        return msg

    def readbuf(self, n):
        """Returns whatever is currently in the buffer. Suitable for large
        buffers.

        Args:
            n: Number of bytes to read.

        """
        if n == 0:
            return ''
        try:
            msg = self.sock.recv(n)
        except BaseException:
            msg = ''
        n2 = min(n - len(msg), n / 2)
        return msg + self.readbuf(n2)

    def readpacket(self, n):
        """Like ``read()``, but may not return everything if the moxa box
        flushes too soon.

        Will probably read whatever arrives in the buffer, up to n or the
        timeout. Use ``read()`` for certainty.

        """
        try:
            msg = self.sock.recv(n)
        except BaseException:
            msg = ''
        return msg

    def read(self, n):
        """Like ``readexactly()``, but returns whatever is in the buffer if it
        can't fill up.

        This replicates the behavior of the read method in pyserial. I feel
        that ``readexactly()`` has better behavior for most applications
        though.

        Args:
            n: Number of bytes to read. Will read at most n bytes.

        Returns:
            str: Returned message of up to n bytes.

        """
        msg = self.readexactly(n)
        n2 = n - len(msg)
        if n2 > 0:
            msg += self.readbuf(n2)
        return msg

    def readline(self, term='\n'):
        msg = ''
        while True:
            c = self.readexactly(1)
            if c == term or c == '':
                return msg
            msg += c

    def readall(self):
        msg = ""
        while True:
            c = self.readexactly(1)
            if c == '\r':
                return msg
            if c == '':
                return False
            msg += c
        return msg

    def write(self, msg):
        """Sends message to the moxa box.

        Args:
            msg (str): Message to send, including terminator (i.e. ``\\r\\n``) if
                needed.

        """
        if self.encoded:
            self.sock.send(msg.encode())
        else:
            self.sock.send(msg)

    def writeread(self, msg):
        self.flushInput()
        self.write(msg)
        return self.readall()

    def flushInput(self):
        """Erases the input buffer at this moment.

        Before I ask for new info from a device, I flush my
        receive buffer to make sure I don't get any garbage in
        front.

        """
        self.sock.setblocking(0)
        try:
            while len(self.sock.recv(1)) > 0:
                pass
        except BaseException:
            pass
        self.sock.setblocking(1)
        self.sock.settimeout(self.__timeout)

    def settimeout(self, timeout):
        """Sets the socket in timeout mode."""
        assert timeout > 0.0
        self.__timeout = timeout
        self.sock.settimeout(timeout)
        # We don't query the socket's timeout or check that they're still
        # correct. Since self.sock e is public this could be the wrong
        # timeout!

    def gettimeout(self):
        return self.__timeout

    timeout = property(gettimeout, settimeout,
                       doc='Communication timeout. Only use timeout mode '
                           + 'with ``timeout > 0.0``.')
