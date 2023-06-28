from socs.agents.hwp_pid.drivers.pid_controller import PID
from socs.testing.device_emulator import create_device_emulator

pid_emu = create_device_emulator(
    {'*W02400000': 'W02\r'}, relay_type='tcp', port=3003)


def test_send_message(pid_emu):
    pid = PID('127.0.0.1', 3003)
    responses = {'ping': 'pong'}
    pid_emu.define_responses(responses)
    resp = pid.send_message('ping')
    assert resp == 'pong'


def test_get_direction(pid_emu):
    pid = PID('127.0.0.1', 3003)
    responses = {'*R02': 'R02400000\r'}
    pid_emu.define_responses(responses)
    pid.get_direction()


def test_set_direction(pid_emu):
    pid = PID('127.0.0.1', 3003)
    responses = {"*W02400000": 'W02\r'}
    pid_emu.define_responses(responses)
    pid.set_direction('0')


def test_decode_read():
    print(PID._decode_read('R02400000'))


def test_decode_read_unknown():
    print(PID._decode_read('R03400000'))


def test_decode_write():
    print(PID._decode_write('W02'))


def test_decode_array():
    print(PID._decode_array(['R02400000']))


def test_decode_measure_unknown():
    assert PID._decode_measure(['R02400000']) == 9.999
