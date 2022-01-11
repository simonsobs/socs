import serial
import time
import subprocess
import shutil
import pytest
import threading


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

    """
    def __init__(self, responses):
        self.responses = responses
        self._read = True

    def create_serial_relay(self):
        self.proc = _setup_socat()
        self.ser = serial.Serial(
            './internal',
            baudrate=57600,
            timeout=5,
        )
        bkg_read = threading.Thread(name='background', target=self.read_serial)
        bkg_read.start()

    def read_serial(self):
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
        print('shutting down background reading')
        self._read = False
        time.sleep(1)
        print('shutting down socat relay')
        self.proc.terminate()
        out, err = self.proc.communicate()
        print(out, err)

    def create_tcp_relay(self):
        pass

    def define_responses(self, responses):
        print(f'responses set to {responses}')
        self.responses = responses
