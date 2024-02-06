import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/hwp_pmx/agent.py', 'hwp_pmx_agent', args=['--log-dir', './logs/'])
run_agent_idle = create_agent_runner_fixture(
    '../socs/agents/hwp_pmx/agent.py', 'hwp_pmx_agent', args=['--mode', 'idle', '--log-dir', './logs/'])
client = create_client_fixture('hwp-pmx')

responses = {
    'meas:volt?': '2',
    'meas:curr?': '1',
    ':system:error?': '+0,"No error"\n',
    'stat:ques?': '0',
    'volt:ext:sour?': 'source_name'
}
kikusui_emu = create_device_emulator(responses, relay_type='tcp', port=5025)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_hwp_rotation_main(wait_for_crossbar, kikusui_emu, run_agent, client):
    client.main.stop()
    resp = client.main.wait()
    assert resp.session['data']['curr'] == 1.0
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_off(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses({
        'output 0': '', 'output?': '0',
    })
    resp = client.set_off()
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_on(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses({
        'output 0': '', 'output?': '0',
    })
    resp = client.set_on()
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_i(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses(
        {'curr 1.000000': '', 'curr?': '1.000000'}
    )
    resp = client.set_i(curr=1)
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_i_lim(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses(
        {'curr:prot 2.000000': '', 'curr:prot?': '2.000000'})
    resp = client.set_i_lim(curr=2)
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_v(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses(
        {'volt 1.000000': '', 'volt?': '1.000000'})
    resp = client.set_v(volt=1)
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_set_v_lim(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses({
        'volt:prot 10.0': '',
        'volt:prot?': '10.000000'
    })
    resp = client.set_v_lim(volt=10)
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_use_ext(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses({
        'volt:ext:sour VOLT': '',
        'volt:ext:sour?': 'source_name',
    })
    resp = client.use_ext()
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']


@pytest.mark.integtest
def test_hwp_rotation_ign_ext(wait_for_crossbar, kikusui_emu, run_agent, client):
    kikusui_emu.update_responses({
        'volt:ext:sour NONE': '',
        'volt:ext:sour?': 'False',
    })
    resp = client.ign_ext()
    print(resp)
    print(resp.session)
    assert resp.status == ocs.OK
    assert resp.session['success']
