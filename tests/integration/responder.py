import serial
import time
import subprocess
import shutil
import pytest
import threading


def _setup_socat():
    # Setup the data relay with socat
    socat = shutil.which('socat')
    cmd = [socat, '-d', '-d', 'pty,link=/home/koopman/port1,b57600', 'pty,link=/home/koopman/port2,b57600']
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

        device.stop_reading()
        device.proc.terminate()
        out, err = device.proc.communicate()
        print(out, err)

    return create_device


class Responder:
    """A mocked device which knows how to respond on various communication
    channels.

    """
    def __init__(self, responses):
        self.responses = responses
        self.read = True

    def create_serial_relay(self):
        self.proc = _setup_socat()
        self.ser = serial.Serial(
            '/home/koopman/port2',
            baudrate=57600,
            timeout=5,
        )
        bkg_read = threading.Thread(name='background', target=self.read_serial)
        bkg_read.start()

    def read_serial(self):
        while self.read:
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

    def stop_reading(self):
        print('shutting down background reading')
        self.read = False
        time.sleep(1)

    def create_tcp_relay(self):
        pass

    def define_responses(self, responses):
        print(f'responses set to {responses}')
        self.responses = responses


responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
             'RDGFIELD?': '+1.0E-01'}
