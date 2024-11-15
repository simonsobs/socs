import os

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()

# Raw bytes message/response for Agent init
init_msg = b'\t\x99\x00\x00\x00\x06\x01\x04\x00\x01\x005'
init_res = b'\t\x99\x00\x00\x00m\x01\x04j\x00\x00\x00\x00\x00\x00\x80\x00\x00\x00\x80\x00A\x06B\x83\xfcjB\x82k\x85B\x84\xe6fB\x85.\xb8C[\t\x0cC[\xf1\x82CZ6\xeeC[\xd8\x00\xbetwG>`\xd6\x00F%\x00\x00\x00\x00)<\x04\x18\x02\x9a\x04u\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/cryomech_cpa/agent.py', 'cryomech_cpa_agent')
run_agent_acq = create_agent_runner_fixture(
    '../socs/agents/cryomech_cpa/agent.py', 'cryomech_cpa_agent', args=['--mode', 'acq'])
client = create_client_fixture('cryomech')
emulator = create_device_emulator({init_msg: init_res}, relay_type='tcp', port=5502, encoding=None)


@pytest.mark.integtest
def test_cryomech_cpa_init(wait_for_crossbar, emulator, run_agent,
                           client):
    resp = client.init.wait()
    resp = client.init.status()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
@pytest.mark.parametrize("state,command", [('on', b'\t\x99\x00\x00\x00\x06\x01\x06\x00\x01\x00\x01'),
                                           ('off', b'\t\x99\x00\x00\x00\x06\x01\x06\x00\x01\x00\xff')])
def test_cryomech_cpa_power_ptc(wait_for_crossbar, emulator, run_agent,
                                client, state, command):
    client.init.wait()

    # response from compressor is an echo of the message
    responses = {command: command}
    emulator.define_responses(responses)

    resp = client.power_ptc(state=state)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_cryomech_cpa_auto_start_acq(wait_for_crossbar, emulator, run_agent_acq, client):
    client.init()

    resp = client.acq.status()

    # just check that the start call worked
    print(resp)
    assert resp.status == ocs.OK


@pytest.mark.integtest
def test_cryomech_cpa_acq(wait_for_crossbar, emulator, run_agent, client):
    client.init()

    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()

    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    # already stopped, but will set self.take_data = False
    resp = client.acq.stop()
    print(resp)


@pytest.mark.integtest
@pytest.mark.parametrize("state,command", [('on', b'\t\x99\x00\x00\x00\x06\x01\x06\x00\x01\x00\x01')])
def test_cryomech_cpa_release_reacquire(wait_for_crossbar, emulator, run_agent_acq,
                                        client, state, command):
    client.init.wait()
    response = {command: command,
                init_msg: init_res}
    emulator.define_responses(response)

    resp = client.power_ptc(state=state)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
