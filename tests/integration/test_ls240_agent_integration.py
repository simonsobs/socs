from dataclasses import asdict

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.agents.lakeshore240.agent import SetValues, UploadCalCurve
from socs.testing.device_emulator import DeviceEmulator, create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/lakeshore240/agent.py', 'ls240_agent')
client = create_client_fixture('LSA240S')

initial_responses = {
    '*IDN?': 'LSCI,MODEL240,LSA240S,1.3',
    'MODNAME?': 'LSA240S',
    'INTYPE? 1': '1,1,0,0,1,1',
    'INNAME? 1': 'Channel 1',
    'INTYPE? 2': '1,1,0,0,1,1',
    'INNAME? 2': 'Channel 2',
    'INTYPE? 3': '1,1,0,0,1,1',
    'INNAME? 3': 'Channel 3',
    'INTYPE? 4': '1,1,0,0,1,1',
    'INNAME? 4': 'Channel 4',
    'INTYPE? 5': '1,1,0,0,1,1',
    'INNAME? 5': 'Channel 5',
    'INTYPE? 6': '1,1,0,0,1,1',
    'INNAME? 6': 'Channel 6',
    'INTYPE? 7': '1,1,0,0,1,1',
    'INNAME? 7': 'Channel 7',
    'INTYPE? 8': '1,1,0,0,1,1',
    'INNAME? 8': 'Channel 8',
    'KRDG? 1': '+1.0E-03',
    'SRDG? 1': '+1.0E+03',
    'KRDG? 2': '+1.0E-03',
    'SRDG? 2': '+1.0E+03',
    'KRDG? 3': '+1.0E-03',
    'SRDG? 3': '+1.0E+03',
    'KRDG? 4': '+1.0E-03',
    'SRDG? 4': '+1.0E+03',
    'KRDG? 5': '+1.0E-03',
    'SRDG? 5': '+1.0E+03',
    'KRDG? 6': '+1.0E-03',
    'SRDG? 6': '+1.0E+03',
    'KRDG? 7': '+1.0E-03',
    'SRDG? 7': '+1.0E+03',
    'KRDG? 8': '+1.0E-03',
    'SRDG? 8': '+1.0E+03',
}
emulator = create_device_emulator(initial_responses, relay_type='serial')


@pytest.mark.integtest
def test_ls240_main(wait_for_crossbar, emulator, run_agent, client):
    client.main.stop()
    resp = client.main.wait()
    print(resp)
    print(resp.session['data'])
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['fields']['Channel_1']['V'] == 1000


@pytest.mark.integtest
def test_ls240_set_values(wait_for_crossbar, emulator: DeviceEmulator, run_agent, client) -> None:
    responses = {'INNAME 1,Channel 01': '',
                 'INTYPE 1,1,1,0,0,1,1': ''}
    emulator.update_responses(responses)

    set_values_params = SetValues(
        channel=1, sensor=1, auto_range=1, range=0, current_reversal=0, units=1,
        enabled=1, name="Channel 01"
    )
    resp = client.set_values(**asdict(set_values_params))
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls240_upload_cal_curve(wait_for_crossbar, emulator, run_agent, client,
                                tmp_path) -> None:
    # Write small calibration curve
    content = "Sensor Model:   DT-670-SD-1.4L\n" + \
              "Serial Number:  D60STND\n" + \
              "Data Format:    2      (Volts/Kelvin)\n" + \
              "SetPoint Limit: 325.0      (Kelvin)\n" + \
              "Temperature coefficient:  1 (Negative)\n" + \
              "Number of Breakpoints:   3\n" + \
              "\n" + \
              "No.   Units      Temperature (K)\n" + \
              "\n" + \
              "  1  0.090681    500.0\n" + \
              "  2  0.112553    490.0\n" + \
              "  3  0.135480    480.0\n"

    cal_file = tmp_path / 'test_cal.340'
    cal_file.write_text(content)
    print(cal_file)
    print(cal_file.read_text())
    assert cal_file.read_text() == content

    # No queries are sent during upload, so rely on the default response of ''
    responses = {'CRVHDR 1,DT-670-SD-1.4L,D60STND,2,325.0,1': ''}
    emulator.update_responses(responses)
    upload_cal_curve_params = UploadCalCurve(
        channel=1, filename=str(cal_file)
    )
    resp = client.upload_cal_curve(**asdict(upload_cal_curve_params))

    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
