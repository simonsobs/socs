import time

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/lakeshore425/agent.py', 'ls425_agent')
run_agent_acq = create_agent_runner_fixture(
    '../socs/agents/lakeshore425/agent.py', 'ls425_agent', args=['--mode', 'acq'])
client = create_client_fixture('LS425')
emulator = create_device_emulator({'*IDN?': 'LSCI,MODEL425,LSA425T,1.3'},
                                  relay_type='serial')


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_ls425_init_lakeshore(wait_for_crossbar, emulator, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls425_auto_start_acq(wait_for_crossbar, emulator, run_agent_acq, client):
    resp = client.init_lakeshore.status()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    time.sleep(3)
    resp = client.acq.status()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.RUNNING.value


@pytest.mark.integtest
def test_ls425_start_acq(wait_for_crossbar, emulator, run_agent, client):
    responses = {'*IDN?': 'LSCI,MODEL425,LSA425T,1.3',
                 'RDGFIELD?': '+1.0E-01'}
    emulator.define_responses(responses)

    resp = client.acq.start(sampling_frequency=1.0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    # We stopped the process with run_once=True, but that will leave us in the
    # RUNNING state
    resp = client.acq.status()
    assert resp.session['op_code'] == OpCode.RUNNING.value

    # Now we request a formal stop, which should put us in STOPPING
    client.acq.stop()
    # this is so we get through the acq loop and actually get a stop command in
    # TODO: get sleep_time in the acq process to be small for testing
    time.sleep(3)
    resp = client.acq.status()
    print(resp)
    print(resp.session)
    assert resp.session['op_code'] in [OpCode.STOPPING.value, OpCode.SUCCEEDED.value]


@pytest.mark.integtest
def test_ls425_operational_status(wait_for_crossbar, emulator, run_agent, client):
    responses = {'OPST?': '132'}
    emulator.define_responses(responses)

    resp = client.operational_status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls425_zero_calibration(wait_for_crossbar, emulator, run_agent, client):
    responses = {'ZCLEAR': '',
                 'ZPROBE': ''}
    emulator.define_responses(responses)

    resp = client.zero_calibration()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls425_any_command(wait_for_crossbar, emulator, run_agent, client):
    responses = {'UNIT 2': '',
                 'UNIT?': '2'}
    emulator.define_responses(responses)

    # Send a command that doesn't expect a response
    resp = client.any_command(command="UNIT 2")
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    # And one that does expect a response
    resp = client.any_command(command="UNIT?")
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
