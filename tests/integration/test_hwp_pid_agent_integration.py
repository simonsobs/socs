import logging
import time

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.hwp_emulator import create_hwp_emulator_fixture

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/hwp_pid/agent.py', 'hwp_pid_agent', args=['--log-dir', './logs/'])
run_agent_idle = create_agent_runner_fixture(
    '../socs/agents/hwp_pid/agent.py', 'hwp_pid_agent', args=['--mode', 'init', '--log-dir', './logs/'])
client = create_client_fixture('hwp-pid')
hwp_emu = create_hwp_emulator_fixture(pid_port=2000, log_level=logging.DEBUG)


def wait_for_main(client):
    while True:
        data = client.main.status().session['data']
        if 'last_updated' in data:
            return
        time.sleep(0.2)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_hwp_rotation_get_state(wait_for_crossbar, hwp_emu, run_agent, client):
    resp = client.get_state()
    state = resp.session['data']
    print(state)
    assert len(state.keys()) > 0


@pytest.mark.integtest
def test_hwp_rotation_set_direction(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.set_direction(direction='0')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    data = client.get_state().session['data']
    assert data['direction'] == '0'

    resp = client.set_direction(direction='1')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    data = client.get_state().session['data']
    assert data['direction'] == '1'


@pytest.mark.integtest
def test_hwp_rotation_set_pid(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.set_pid(p=0.2, i=63, d=0)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_tune_stop(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.tune_stop()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_scale(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.set_scale()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_declare_freq(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.declare_freq(freq=0)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_tune_freq(wait_for_crossbar, hwp_emu, run_agent, client):
    wait_for_main(client)
    resp = client.tune_freq()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
