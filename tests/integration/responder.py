import serial
import time
import subprocess
import shutil
import pytest
import threading


def create_responder_fixture(responses):
    @pytest.fixture()
    def create_device():
        device = Responder(responses)
        device.create_serial_relay()

        yield device

        device.shutdown()

    return create_device


class Responder:
    """A mocked device which knows how to respond on various communication
    channels.

    Args:
        responses (dict): Initial responses, any response required by Agent
            startup, if any.

    Attributes:
        responses (dict): Current set of responses the Responder would give

    """
    def __init__(self, responses):
        self.responses = responses
        self._read = True

    @staticmethod
    def _setup_socat():
        """Setup a data relay with socat.

        The "./responder" link is the external end of the relay, which the Agent
        should connect to. "./internal" is used within the Responder object to accept
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
        "responder" end of the relay.

        Next it creates a thread to read commands sent to the serial relay in
        the background. This allows responses to be defined within a test using
        Responder.define_responses() after instantiation of the Responder
        object within a given test.

        """
        self.proc = self._setup_socat()
        self.ser = serial.Serial(
            './internal',
            baudrate=57600,
            timeout=5,
        )
        bkg_read = threading.Thread(name='background', target=self._read_serial)
        bkg_read.start()

    def _read_serial(self):
        """Loop until shutdown, reading any commands sent over the relay.
        Respond immediately to a command with the response in self.responses.

        """
        self._read = True

        while self._read:
            if self.ser.in_waiting > 0:
                msg = self.ser.readline().strip().decode('utf-8')
                print(f"{msg=}")

                if self.responses is None:
                    continue

                try:
                    if isinstance(self.responses[msg], list):
                        response = self.responses[msg].pop(0)
                    else:
                        response = self.responses[msg]

                    print(f'{response=}')
                    self.ser.write((response + '\r\n').encode('utf-8'))
                except Exception as e:
                    print(f"encountered error {e}")
            time.sleep(0.01)

    def __del__(self):
        self.shutdown()

    def shutdown(self):
        """Shutdown communication on the configured relay. This will stop any
        attempt to read communication on the relay, as well as shutdown the relay
        itself.

        """
        #print('shutting down background reading')
        self._read = False
        time.sleep(1)
        #print('shutting down socat relay')
        self.proc.terminate()
        out, err = self.proc.communicate()
        #print(out, err)

    def create_tcp_relay(self):
        pass

    def define_responses(self, responses):
        """Define what responses are available to reply with on the configured
        communication relay.

        Args:
            responses (dict): Dictionary of commands: response. Values can be a
                list, in which case the responses in the list are popped and given in order
                until depleted.

        Examples:
            The given responses might look like::

            >>> responses = {'KRDG? 1': '+1.7E+03'}
            >>> responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
                             'RDGFIELD?': ['+1.0E-01', '+1.2E-01', '+1.4E-01']}

        """
        print(f'responses set to {responses}')
        self.responses = responses
