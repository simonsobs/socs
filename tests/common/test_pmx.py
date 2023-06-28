import time

import pytest

from socs.common.pmx import PMX, Command
from socs.testing.device_emulator import create_device_emulator

tcp_emulator = create_device_emulator({'ping': 'pong\r',
                                       'SYST:REM': 'test'},
                                      'tcp', 19002)


# Tried this as a fixture, but connections weren't cleaning up properly.
def create_command():
    # Connection might not work on first attempt
    for i in range(5):
        try:
            pmx = PMX(tcp_ip='127.0.0.1', tcp_port=19002, timeout=0.1)
            cmd = Command(pmx)
            break
        except ConnectionRefusedError:
            print("Could not connect, waiting and trying again.")
            time.sleep(1)
    return cmd


@pytest.mark.integtest
def test_pmx_create_command(tcp_emulator):
    create_command()


@pytest.mark.integtest
def test_pmx_destructor(tcp_emulator):
    cmd = create_command()
    del cmd


@pytest.mark.integtest
def test_pmx_cmd_on(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'OUTP ON': '',
                                   'OUTP?': 'on'})

    cmd.user_input('on')


@pytest.mark.integtest
def test_pmx_cmd_off(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'OUTP OFF': '',
                                   'OUTP?': 'off'})

    cmd.user_input('off')


@pytest.mark.integtest
def test_pmx_cmd_set_voltage(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'VOLT 1': '',
                                   'VOLT?': '1'})

    cmd.user_input('V 1')


@pytest.mark.integtest
def test_pmx_cmd_set_current(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'CURR 1': '',
                                   'CURR?': '1'})

    cmd.user_input('C 1')


@pytest.mark.integtest
def test_pmx_cmd_set_voltage_limit(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'VOLT:PROT 1': '',
                                   'VOLT:PROT?': '1'})

    cmd.user_input('VL 1')


@pytest.mark.integtest
def test_pmx_cmd_set_current_limit(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'CURR:PROT 1': '',
                                   'CURR:PROT?': '1'})

    cmd.user_input('CL 1')


@pytest.mark.integtest
def test_pmx_cmd_use_external_voltage(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'VOLT:EXT:SOUR VOLT': '',
                                   'VOLT:EXT:SOUR?': 'source_name'})

    assert 'source_name' in cmd.user_input('U')


@pytest.mark.integtest
def test_pmx_cmd_ignore_external_voltage(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'VOLT:EXT:SOUR NONE': '',
                                   'VOLT:EXT:SOUR?': 'False'})

    assert 'False' in cmd.user_input('I')


@pytest.mark.integtest
def test_pmx_cmd_check_voltage(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'MEAS:VOLT?': '1'})

    msg, val = cmd.user_input('V?')
    assert val == 1


@pytest.mark.integtest
def test_pmx_cmd_check_current(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'MEAS:CURR?': '1'})

    msg, val = cmd.user_input('C?')
    assert val == 1


@pytest.mark.integtest
def test_pmx_cmd_check_voltage_current(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'MEAS:VOLT?': '2',
                                   'MEAS:CURR?': '1'})

    volt, curr = cmd.user_input('VC?')
    assert volt == 2
    assert curr == 1


@pytest.mark.integtest
def test_pmx_cmd_check_output(tcp_emulator):
    cmd = create_command()
    tcp_emulator.define_responses({'OUTP?': '0'})
    msg, val = cmd.user_input('O?')
    assert val == 0

    tcp_emulator.define_responses({'OUTP?': '1'})
    msg, val = cmd.user_input('O?')
    assert val == 1

    tcp_emulator.define_responses({'OUTP?': '2'})
    msg, val = cmd.user_input('O?')
    assert val == 2
