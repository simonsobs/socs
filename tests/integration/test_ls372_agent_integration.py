import os
import pytest

import ocs
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from integration.util import create_crossbar_fixture

pytest_plugins = ("docker_compose")

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()


run_agent = create_agent_runner_fixture(
                '../agents/lakeshore372/LS372_agent.py',
                'ls372')
client = create_client_fixture('LSASIM')
wait_for_crossbar = create_crossbar_fixture()


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_ls372_init_lakeshore(wait_for_crossbar, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_enable_control_chan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.enable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_disable_control_chan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.disable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_start_acq(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.acq.start(sample_heater=False, run_once=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    client.acq.wait()
    resp = client.acq.status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_range(range=1e-3, heater='sample', wait=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation_mode(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation_mode(channel=1, mode='current')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation(channel=1, value=1e-9)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_excitation(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_excitation(channel=1, value=1e-9)
    resp = client.get_excitation(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['excitation'] == 1e-9


@pytest.mark.integtest
def test_ls372_set_resistance_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_resistance_range(channel=1, resistance_range=2)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_resistance_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_resistance_range(channel=1, resistance_range=2)
    resp = client.get_resistance_range(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['resistance_range'] == 2


@pytest.mark.integtest
def test_ls372_set_dwell(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_dwell(channel=1, dwell=3)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_dwell(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_dwell(channel=1, dwell=3)
    resp = client.get_dwell(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['dwell_time'] == 3


@pytest.mark.integtest
def test_ls372_set_pid(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_pid(P=40, I=2, D=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_active_channel(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_active_channel(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_autoscan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_autoscan(autoscan=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_output_mode(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_output_mode(heater='still', mode='Off')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_output(heater='still', output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_still_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_still_output(output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_still_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.get_still_output()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
