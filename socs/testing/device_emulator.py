import shutil
import socket
import subprocess
import threading
import time

import pytest
import serial


def create_device_emulator(responses, relay_type, port=9001, encoding='utf-8'):
    """Create a device emulator fixture.

    This provides a device emulator that can be used to mock a device during
    testing.

    Args:
        responses (dict): Dictionary with commands as keys, and responses as
            values. See :class:`.DeviceEmulator` for details.
        relay_type (str): Communication relay type. Either 'serial' or 'tcp'.
        port (int): Port for the TCP relay to listen for connections on.
            Defaults to 9001. Only used if relay_type is 'tcp'.
        encoding (str): Encoding for the messages and responses. See
            :func:`socs.testing.device_emulator.DeviceEmulator` for more
            details.

    Returns:
        function:
            A pytest fixture that creates a Device emulator of the specified
            type.

    """
    if relay_type not in ['serial', 'tcp']:
        raise NotImplementedError(f"relay_type '{relay_type}' is not"
                                  + "implemented or is an invalid type")

    @pytest.fixture()
    def create_device():
        device = DeviceEmulator(responses, encoding)

        if relay_type == 'serial':
            device.create_serial_relay()
        elif relay_type == 'tcp':
            device.create_tcp_relay(port)

        yield device

        device.shutdown()

    return create_device


class DeviceEmulator:
    """A mocked device which knows how to respond on various communication
    channels.

    Args:
        responses (dict): Initial responses, any response required by Agent
            startup, if any.
        encoding (str): Encoding for the messages and responses.
            DeviceEmulator will try to encode and decode messages with the
            given encoding. No encoding is used if set to None. That can be
            useful if you need to use raw data from your hardware. Defaults
            to 'utf-8'.

    Attributes:
        responses (dict): Current set of responses the DeviceEmulator would
            give. Should all be strings, not bytes-like.
        default_response (str): Default response to send if a command is
            unrecognized. No response is sent and an error message is logged if
            a command is unrecognized and the default response is set to None.
            Defaults to None.
        encoding (str): Encoding for the messages and responses, set by the
            encoding argument.
        _type (str): Relay type, either 'serial' or 'tcp'.
        _read (bool): Used to stop the background reading of data recieved on
            the relay.
        _conn (socket.socket): TCP connection for use in 'tcp' relay.

    """

    def __init__(self, responses, encoding='utf-8'):
        self.responses = responses
        self.default_response = None
        self.encoding = encoding
        self._type = None
        self._read = True
        self._conn = None

    @staticmethod
    def _setup_socat():
        """Setup a data relay with socat.

        The "./responder" link is the external end of the relay, which the Agent
        should connect to. "./internal" is used within the DeviceEmulator object to accept
        commands and to respond to the Agent.

        """
        socat = shutil.which('socat')
        cmd = [socat, '-d', '-d', 'pty,link=./responder,b57600', 'pty,link=./internal,b57600']
        proc = subprocess.Popen(cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
        time.sleep(1)

        return proc

    def create_serial_relay(self):
        """Create the serial relay, emulating a hardware device connected over
        serial.

        This first uses ``socat`` to setup a relay. It then connects to the
        "internal" end of the relay, ready to receive communications sent to the
        "responder" end of the relay. This end of the relay is located at
        ``./responder``. You will need to configure your Agent to use that path for
        communication.

        Next it creates a thread to read commands sent to the serial relay in
        the background. This allows responses to be defined within a test using
        DeviceEmulator.define_responses() after instantiation of the DeviceEmulator
        object within a given test.

        """
        self._type = 'serial'
        self.proc = self._setup_socat()
        self.ser = serial.Serial(
            './internal',
            baudrate=57600,
            timeout=5,
        )
        bkg_read = threading.Thread(name='background',
                                    target=self._read_serial)
        bkg_read.start()

    def _get_response(self, msg):
        """Determine the response to a given message.

        Args:
            msg (str): Command string to get the response for.

        Returns:
            str: Response string. Will return None if a valid response is not
                 found.

        """
        if self.responses is None:
            return

        if msg not in self.responses and self.default_response is not None:
            return self.default_response

        try:
            if isinstance(self.responses[msg], list):
                response = self.responses[msg].pop(0)
            else:
                response = self.responses[msg]
        except Exception as e:
            print(f"encountered error {e}")
            response = None

        return response

    def _read_serial(self):
        """Loop until shutdown, reading any commands sent over the relay.
        Respond immediately to a command with the response in self.responses.

        """
        self._read = True

        while self._read:
            if self.ser.in_waiting > 0:
                msg = self.ser.readline()
                if self.encoding:
                    msg = msg.strip().decode(self.encoding)
                print(f"msg='{msg}'")

                response = self._get_response(msg)

                # Avoid user providing bytes-like response
                if isinstance(response, bytes) and self.encoding is not None:
                    response = response.decode()

                if response is None:
                    continue

                print(f"response='{response}'")
                if self.encoding:
                    response = (response + '\r\n').encode(self.encoding)
                self.ser.write(response)

            time.sleep(0.01)

    def __del__(self):
        self.shutdown()

    def shutdown(self):
        """Shutdown communication on the configured relay. This will stop any
        attempt to read communication on the relay, as well as shutdown the relay
        itself.

        """
        # print('shutting down background reading')
        self._read = False
        time.sleep(1)
        if self._type == 'serial':
            # print('shutting down socat relay')
            self.proc.terminate()
            out, err = self.proc.communicate()
            # print(out, err)
        if self._type == 'tcp':
            # print('shutting down background tcp relay')
            if self._conn:
                self._conn.close()
                self._sock.close()

    def _read_socket(self, port):
        """Loop until shutdown, reading any commands sent over the relay.
        Respond immediately to a command with the response in self.responses.

        Args:
            port (int): Port for the TCP relay to listen for connections on.

        """
        self._read = True

        # Listen for connections
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(('127.0.0.1', port))
        self._sock.listen(1)
        print("Device emulator waiting for tcp client connection")
        self._conn, client_address = self._sock.accept()
        print(f"Client connection made from {client_address}")

        while self._read:
            try:
                msg = self._conn.recv(4096)
            # Was seeing this on tests in the cryomech agent
            except ConnectionResetError:
                print('Caught connection reset on Agent clean up')
                break
            if self.encoding:
                msg = msg.strip().decode(self.encoding)
            if msg:
                print(f"msg='{msg}'")

                response = self._get_response(msg)

                # Avoid user providing bytes-like response
                if isinstance(response, bytes) and self.encoding is not None:
                    response = response.decode()

                if response is None:
                    continue

                print(f"response='{response}'")
                if self.encoding:
                    response = response.encode(self.encoding)
                self._conn.sendall(response)

            time.sleep(0.01)

        self._conn.close()
        self._sock.close()

    def create_tcp_relay(self, port):
        """Create the TCP relay, emulating a hardware device connected over
        TCP.

        Creates a thread to read commands sent to the TCP relay in the
        background. This allows responses to be defined within a test using
        DeviceEmulator.define_responses() after instantiation of the
        DeviceEmulator object within a given test.

        Args:
            port (int): Port for the TCP relay to listen for connections on.

        """
        self._type = 'tcp'
        bkg_read = threading.Thread(name='background',
                                    target=self._read_socket,
                                    kwargs={'port': port})
        bkg_read.start()

    def define_responses(self, responses, default_response=None):
        """Define what responses are available to reply with on the configured
        communication relay.

        Args:
            responses (dict): Dictionary of commands: response. Values can be a
                list, in which case the responses in the list are popped and
                given in order until depleted.
            default_response (str): Default response to send if a command is
                unrecognized. No response is sent and an error message is
                logged if a command is unrecognized and the default response is
                set to None. Defaults to None.

        Examples:
            The given responses might look like::

                >>> responses = {'KRDG? 1': '+1.7E+03'}
                >>> responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
                                 'RDGFIELD?': ['+1.0E-01', '+1.2E-01', '+1.4E-01']}

        Notes:
            The DeviceEmulator will handle encoding/decoding. The responses
            defined should all be strings, not bytes-like, unless you set
            ``encoding=None``.

        """
        print(f"responses set to {responses}")
        self.responses = responses
        print(f"default response set to '{default_response}'")
        self.default_response = default_response
