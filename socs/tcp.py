import selectors
import socket


class TCPInterface:
    """Interface class for connecting to devices using TCP.

    Parameters
    ----------
    ip_address : str
        IP address of the device.
    port : int
        Associated port for TCP communication.
    timeout : float
        Duration in seconds that operations wait before giving up.

    Attributes
    ----------
    ip_address : str
        IP address of the device.
    port : int
        Associated port for TCP communication.
    timeout : float
        Duration in seconds that operations wait before giving up.
    comm : socket.socket
        Socket object that forms the connection to the device.

    """

    def __init__(self, ip_address, port, timeout):
        self.ip_address = ip_address
        self.port = int(port)
        self.timeout = timeout
        self.comm = self._connect((self.ip_address, self.port))

    def _connect(self, address):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect(address)
        except TimeoutError:
            print(f"Connection not established within {self.timeout}.")
            return
        except OSError as e:
            print(f"Unable to connect. {e}")
            return
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} while connecting:")
            print(f"  {e}")
            return
        return sock

    def _reset(self):
        print("Resetting the connection to the device.")
        self.comm = self._connect((self.ip_address, self.port))

    def send(self, msg):
        """Send message to socket.

        This method will try to send the message and if it runs into any issues
        will try to re-establish the socket connection before trying to send
        the message again. If it fails a second time it raises an exception.

        If the connection has failed to reset from a previous ``send``, or has
        not yet been established, it will first try to connnect before sending
        the message. If it fails to establish the connection it will raise an
        exception.

        Parameters
        ----------
        msg : str
            Message string to send on socket.

        Raises
        ------
        ConnectionError
            Raised if the communication fails for any reason.

        """
        if self.comm is None:
            print("Connection not established.")
            self._reset()
            if self.comm is None:
                raise ConnectionError("Unable to establish connection.")

        try:
            self.comm.sendall(msg)
            return
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Connection error: {e}")
            self._reset()
        except TimeoutError as e:
            print(f"Timeout error while writing: {e}")
            self._reset()
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} during send:")
            print(f"  {e}")
            self._reset()

        # Try a second time before giving up
        try:
            self.comm.sendall(msg)
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"Connection error: {e}")
            raise ConnectionError
        except TimeoutError as e:
            print(f"Timeout error while writing: {e}")
            raise ConnectionError
        except AttributeError:
            raise ConnectionError("Unable to reset connection.")
        except Exception as e:
            print(f"Caught unexpected {type(e).__name__} during send:")
            print(f"  {e}")
            raise ConnectionError

    def _check_ready(self):
        """Check socket is ready to read from."""
        if self.comm is None:
            raise ConnectionError("Connection not established, not ready to read.")

        sel = selectors.DefaultSelector()
        sel.register(self.comm, selectors.EVENT_READ)
        if not sel.select(self.timeout):
            raise ConnectionError("Socket not ready to read. Possible timeout.")

    def recv(self, bufsize=4096):
        """Receive response from the device.

        This method will check if the socket is ready to be read from before
        performing the recv. If there is no data to read, or the socket is
        otherwise unready an exception is raised.

        Parameters
        ----------
        bufsize : int
            Amount of data to be recieved in bytes. Defaults to 4096.

        Returns
        -------
        ``str`` or ``bytes``
            The response from the device. The return type
            depends on the device.

        Raises
        ------
        ConnectionError
            Raised if the socket is not ready to read from.

        """
        self._check_ready()
        data = self.comm.recv(bufsize)
        return data

    def __del__(self):
        if self.comm:
            self.comm.close()
