import socket
import time

import pytest

from socs.testing import device_emulator

tcp_emulator = device_emulator.create_device_emulator({'ping': 'pong'},
                                                      'tcp', 9001)


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
