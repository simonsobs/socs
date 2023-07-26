import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/hwp_pid/agent.py', 'hwp_pid_agent', args=['--log-dir', './logs/'])
run_agent_idle = create_agent_runner_fixture(
    '../socs/agents/hwp_pid/agent.py', 'hwp_pid_agent', args=['--mode', 'init', '--log-dir', './logs/'])
client = create_client_fixture('hwp-pid')
pid_emu = create_device_emulator(
    {'*W02400000': 'W02\r'}, relay_type='tcp', port=2000)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_hwp_rotation_failed_connection_pid(wait_for_crossbar, run_agent_idle, client):
    resp = client.init_connection.start()
    print(resp)
    # We can't really check anything here, the agent's going to exit during the
    # init_conneciton task because it cannot connect to the PID controller.


@pytest.mark.integtest
def test_hwp_rotation_get_direction(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*R02': 'R02400000\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.get_direction()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    # Test when in reverse
    responses = {'*W02401388': 'W02\r',
                 '*R02': 'R02401388\r'}
    pid_emu.define_responses(responses)

    client.set_direction(direction='1')
    resp = client.get_direction()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_direction(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*W02400000': 'W02\r',
                 '*W02401388': 'W02\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_direction(direction='0')
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    resp = client.set_direction(direction='1')
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_pid(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*W1700C8': 'W17\r',
                 '*W18003F': 'W18\r',
                 '*W190000': 'W19\r',
                 '*Z02': 'Z02\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_pid(p=0.2, i=63, d=0)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_tune_stop(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*W0C83': 'W0C\r',
                 '*W01400000': 'W01\r',
                 '*R01': 'R01400000\r',
                 '*Z02': 'Z02\r',
                 '*W1700C8': 'W17\r',
                 '*W180000': 'W18\r',
                 '*W190000': 'W19\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.tune_stop()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_get_freq(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*X01': 'X010.000\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.get_freq()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_scale(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*W14102710': 'W14\r',
                 '*W03302710': 'W03\r',
                 '*Z02': 'Z02\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_scale()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_declare_freq(wait_for_crossbar, pid_emu, run_agent, client):
    client.init_connection.wait()  # wait for connection to be made
    resp = client.declare_freq(freq=0)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_tune_freq(wait_for_crossbar, pid_emu, run_agent, client):
    responses = {'*W0C81': 'W0C\r',
                 '*W01400000': 'W01\r',
                 '*R01': 'R01400000\r',
                 '*Z02': 'Z02\r',
                 '*W1700C8': 'W17\r',
                 '*W18003F': 'W18\r',
                 '*W190000': 'W19\r'}
    pid_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.tune_freq()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
