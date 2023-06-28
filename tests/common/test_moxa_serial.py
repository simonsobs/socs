import time

import pytest

from socs.common import moxa_serial
from socs.testing.device_emulator import create_device_emulator

tcp_emulator = create_device_emulator({'ping': 'pong\r'},
                                      'tcp', 19001)


# Tried this as a fixture, but connections weren't cleaning up properly.
def create_tcpserver():
    # Connection might not work on first attempt
    for i in range(5):
        try:
            ser = moxa_serial.Serial_TCPServer(('127.0.0.1', 19001), 0.1)
            break
        except ConnectionRefusedError:
            print("Could not connect, waiting and trying again.")
            time.sleep(1)
    return ser


@pytest.mark.integtest
def test_moxa_serial_create_serial_tcpserver(tcp_emulator):
    create_tcpserver()


@pytest.mark.integtest
def test_moxa_serial_write(tcp_emulator):
    ser = create_tcpserver()
    ser.write('ping')


@pytest.mark.integtest
def test_moxa_serial_writeread(tcp_emulator):
    ser = create_tcpserver()
    response = ser.writeread('ping')
    assert response == 'pong'


@pytest.mark.integtest
def test_moxa_serial_write_readline(tcp_emulator):
    ser = create_tcpserver()
    ser.write('ping')
    assert ser.readline() == 'pong\r'
