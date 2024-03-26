import time

import pytest

from socs.common import moxa_serial
from socs.testing.device_emulator import create_device_emulator

tcp_emulator = create_device_emulator({'ping': 'pong\r'},
                                      'tcp')


# Tried this as a fixture, but connections weren't cleaning up properly.
def create_tcpserver(port):
    # Connection might not work on first attempt
    for i in range(5):
        try:
            ser = moxa_serial.Serial_TCPServer(('127.0.0.1', port), 0.1)
            break
        except ConnectionRefusedError:
            print("Could not connect, waiting and trying again.")
            time.sleep(1)
    return ser


@pytest.mark.integtest
def test_moxa_serial_create_serial_tcpserver(tcp_emulator):
    create_tcpserver(tcp_emulator.port)


@pytest.mark.integtest
def test_moxa_serial_write(tcp_emulator):
    ser = create_tcpserver(tcp_emulator.port)
    ser.write('ping')


@pytest.mark.integtest
def test_moxa_serial_writeread(tcp_emulator):
    ser = create_tcpserver(tcp_emulator.port)
    response = ser.writeread('ping')
    assert response == 'pong'


@pytest.mark.integtest
def test_moxa_serial_write_readline(tcp_emulator):
    ser = create_tcpserver(tcp_emulator.port)
    ser.write('ping')
    assert ser.readline() == 'pong\r'
