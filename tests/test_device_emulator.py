import time
import socket
import pytest
from telnetlib import Telnet

from socs.testing import device_emulator


tcp_emulator = device_emulator.create_device_emulator({'ping': 'pong'},
                                                      'tcp', 9001)
telnet_emulator = device_emulator.create_device_emulator({'ping': 'pong'},
                                                         'telnet', 9002)


def test_create_device_emulator_invalid_type():
    with pytest.raises(NotImplementedError):
        device_emulator.create_device_emulator({}, relay_type='test')


def test_create_device_emulator_tcp_relay(tcp_emulator):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        # Connection might not work on first attempt
        for i in range(5):
            try:
                s.connect(('127.0.0.1', 9001))
                break
            except ConnectionRefusedError:
                print("Could not connect, waiting and trying again.")
                time.sleep(1)
        s.sendall(b'ping')
        data = s.recv(1024).decode()
    assert data == 'pong'


def test_create_device_emulator_telnet_relay(telnet_emulator):
    with Telnet() as tn:
        for i in range(5):
            try:
                tn.open('localhost', 9002)
                break
            except ConnectionRefusedError:
                print("Could not connect, waiting and trying again.")
                time.sleep(1)
        tn.write(b'ping\r\n')
        response = tn.read_some()
        print(response)

    print('outside')
