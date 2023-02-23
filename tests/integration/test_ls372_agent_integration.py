import os

import ocs
import pytest
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

pytest_plugins = ("docker_compose")

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()


run_agent = create_agent_runner_fixture(
    '../socs/agents/lakeshore372/agent.py',
    'ls372',
    args=["--log-dir", "./logs/"])
client = create_client_fixture('LSASIM')
wait_for_crossbar = create_crossbar_fixture()


def build_init_responses():
    values = {'*IDN?': 'LSCI,MODEL372,LSASIM,1.3',
              'SCAN?': '01,1',
              'INSET? A': '0,010,003,00,1',
              'INNAME? A': 'Input A',
              'INTYPE? A': '1,04,0,15,0,2',
              'TLIMIT? A': '+0000',
              'OUTMODE? 0': '2,6,1,0,0,001',
              'HTRSET? 0': '+120.000,8,+0000.00,1',
              'OUTMODE? 2': '4,16,1,0,0,001',
              'HTRSET? 2': '+120.000,8,+0000.00,1'}

    for i in range(1, 17):
        values[f'INSET? {i}'] = '1,007,003,21,1'
        values[f'INNAME? {i}'] = f'Channel {i:02}'
        values[f'INTYPE? {i}'] = '0,07,1,10,0,1'
        values[f'TLIMIT? {i}'] = '+0000'

    # Heaters
    values.update({'RANGE? 0': '0',
                   'RANGE? 2': '1',
                   'STILL?': '+10.60',
                   'HTR?': '+00.0005E+00'})

    # Senor readings
    values.update({'KRDG? 1': '+293.873E+00',
                   'SRDG? 1': '+108.278E+00',
                   'KRDG? A': '+00.0000E-03',
                   'SRDG? A': '+000.000E+09'})

    return values


emulator = create_device_emulator(build_init_responses(), relay_type='tcp', port=7777)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_ls372_init_lakeshore(wait_for_crossbar, emulator, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_enable_control_chan(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.enable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_disable_control_chan(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.disable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_start_acq(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.acq.start(sample_heater=False, run_once=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    client.acq.wait()
    resp = client.acq.status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_range(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_range(range=1e-3, heater='sample', wait=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation_mode(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation_mode(channel=1, mode='current')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation(channel=1, value=1e-9)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_excitation(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.get_excitation(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['excitation'] == 2e-3


@pytest.mark.integtest
def test_ls372_set_resistance_range(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_resistance_range(channel=1, resistance_range=2)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_resistance_range(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    client.set_resistance_range(channel=1, resistance_range=2)
    resp = client.get_resistance_range(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['resistance_range'] == 63.2


@pytest.mark.integtest
def test_ls372_set_dwell(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_dwell(channel=1, dwell=3)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_dwell(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.get_dwell(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['dwell_time'] == 7


@pytest.mark.integtest
def test_ls372_set_pid(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_pid(P=40, I=2, D=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_active_channel(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_active_channel(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_autoscan(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_autoscan(autoscan=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_output_mode(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_output_mode(heater='still', mode='Off')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_output(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_output(heater='still', output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_still_output(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_still_output(output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_still_output(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.get_still_output()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_engage_channel(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.engage_channel(channel=2, state='on')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_calibration_curve(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.set_calibration_curve(channel=4, curve_number=28)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_input_setup(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    resp = client.get_input_setup(channel=4)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_sample_custom_pid(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    response = {'SCAN?': '02, 0',
                'KRDG? 2': '102E-3',
                'RANGE? 0': '5',
                'SRDG? 2': '15.00E+03',
                'HTRSET? 0': '50,8,+0003.00,1'}
    emulator.define_responses(response)
    resp = client.custom_pid.start(setpoint=0.102, heater='sample', channel=2,
                                   P=2500, I=1 / 20, update_time=0, sample_heater_range=3.16e-3,
                                   test_mode=True)
    print('resp:', resp)
    print('resp.status', resp.status)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    client.custom_pid.wait()
    resp = client.custom_pid.status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_still_custom_pid(wait_for_crossbar, emulator, run_agent, client):
    client.init_lakeshore()
    response = {'SCAN?': '05, 0',
                'KRDG? 5': '95E-3',
                'SRDG? 5': '15.00E+03',
                'RANGE? 2': '1',
                'OUTMODE? 2': '4,5,1,0,0,001',
                'HTRSET? 2': '+1020.000,8,+0000.00,1'}
    emulator.define_responses(response)
    resp = client.custom_pid.start(setpoint=0.95, heater='still', channel=5,
                                   P=0, I=1. / 7, update_time=0, test_mode=True)
    print('resp:', resp)
    print('resp.status', resp.status)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    client.custom_pid.wait()
    resp = client.custom_pid.status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
