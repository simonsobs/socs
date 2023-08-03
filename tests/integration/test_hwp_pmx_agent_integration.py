import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/hwp_pmx/agent.py', 'hwp_pmx_agent', args=['--log-dir', './logs/'])
run_agent_idle = create_agent_runner_fixture(
    '../socs/agents/hwp_pmx/agent.py', 'hwp_pmx_agent', args=['--mode', 'idle', '--log-dir', './logs/'])
client = create_client_fixture('hwp-pmx')
kikusui_emu = create_device_emulator({}, relay_type='tcp', port=5025)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


# This ends up hanging for some reason that I can't figure out at the moment.
# @pytest.mark.integtest
# def test_hwp_pmx_failed_connection_kikusui(wait_for_crossbar, run_agent_idle, client):
#     resp = client.init_connection.start()
#     print(resp)
#     # We can't really check anything here, the agent's going to exit during the
#     # init_conneciton task because it cannot connect to the Kikusui.


@pytest.mark.integtest
def test_hwp_rotation_set_on(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'output 1': '',
                 'output?': '1'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_on()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_off(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'output 0': '',
                 'output?': '0'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_off()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_i(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'curr 1.000000': '',
                 'curr?': '1.000000'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_i(curr=1)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_i_lim(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'curr:prot 2.000000': '',
                 'curr:prot?': '2.000000'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_i_lim(curr=2)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_v(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'volt 1.000000': '',
                 'volt?': '1.000000'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_v(volt=1)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_set_v_lim(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'volt:prot 10.000000': '',
                 'volt:prot?': '10.000000'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.set_v_lim(volt=10)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_use_ext(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'volt:ext:sour VOLT': '',
                 'volt:ext:sour?': 'source_name'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.use_ext()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_ign_ext(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'volt:ext:sour NONE': '',
                 'volt:ext:sour?': 'False'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.ign_ext()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_hwp_rotation_acq(wait_for_crossbar, kikusui_emu, run_agent, client):
    responses = {'meas:volt?': '2',
                 'meas:curr?': '1',
                 ':system:error?': '+0,"No error"\n',
                 'stat:ques?': '0'}
    kikusui_emu.define_responses(responses)

    client.init_connection.wait()  # wait for connection to be made
    resp = client.acq.start(test_mode=True)
    assert resp.status == ocs.OK

    resp = client.acq.wait(timeout=20)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
