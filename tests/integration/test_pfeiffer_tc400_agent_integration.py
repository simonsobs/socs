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


def chksum_msg(msg):
    """Create and append the checksum ot a message."""
    msg += "{:03d}\r".format(sum([ord(x) for x in msg]) % 256)
    return msg


def format_reply(data):
    """Produce full message string we expect back from the TC400, provided only
    the data segment.

    The driver code reads the response, and only inspects the data section of
    the telegram. This function is meant to make preparing the responses a bit
    easier, by putting in something somewhat sensible for the rest of the
    telegram.

    Parameters:
        data (str): Data string to package into telegram.

    Returns:
        str: The full telegram string that is emulating the response from the
            TC400.

    """
    return chksum_msg('001' + '10' + '010' + '{:02d}'.format(len(data)) + data)


wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/pfeiffer_tc400/agent.py', 'tc400_agent')
client = create_client_fixture('pfeifferturboA')
emulator = create_device_emulator({}, relay_type='tcp')


@pytest.mark.integtest
def test_pfeiffer_tc400_init_lakeshore(wait_for_crossbar, emulator, run_agent,
                                       client):
    resp = client.init()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_on(wait_for_crossbar, emulator, run_agent,
                                      client):
    client.init()

    responses = {'0011001006111111015': format_reply('111111'),  # ready_turbo()
                 '0011002306111111019': format_reply('111111'),  # turn_turbo_motor_on()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_on()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_on_not_ready(wait_for_crossbar, emulator,
                                                run_agent, client):
    client.init()

    responses = {'0011001006111111015': format_reply('000000'),  # ready_turbo()
                 '0011002306111111019': format_reply('111111'),  # turn_turbo_motor_on()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_on()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.FAILED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_on_failed(wait_for_crossbar, emulator,
                                             run_agent, client):
    client.init()

    responses = {'0011001006111111015': format_reply('111111'),  # ready_turbo()
                 '0011002306111111019': format_reply('000000'),  # turn_turbo_motor_on()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_on()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.FAILED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_off(wait_for_crossbar, emulator, run_agent,
                                       client):
    client.init()

    responses = {'0011002306000000013': format_reply('000000'),  # turn_turbo_motor_off()
                 '0011001006000000009': format_reply('111111'),  # unready_turbo()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_off()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_off_failed(wait_for_crossbar, emulator,
                                              run_agent, client):
    client.init()

    responses = {'0011002306000000013': format_reply('111111'),  # turn_turbo_motor_off()
                 '0011001006000000009': format_reply('111111'),  # unready_turbo()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_off()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.FAILED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_off_failed_unready(wait_for_crossbar,
                                                      emulator, run_agent,
                                                      client):
    client.init()

    responses = {'0011002306000000013': format_reply('000000'),  # turn_turbo_motor_off()
                 '0011001006000000009': format_reply('000000'),  # unready_turbo()
                 }
    emulator.define_responses(responses)

    resp = client.turn_turbo_off()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.FAILED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_acknowledge_turbo_errors(wait_for_crossbar, emulator,
                                                 run_agent, client):
    client.init()

    responses = {'0011000906111111023': format_reply('111111'),  # acknowledge_turbo_errors()
                 }
    emulator.define_responses(responses)

    resp = client.acknowledge_turbo_errors()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_pfeiffer_tc400_acq(wait_for_crossbar, emulator, run_agent, client):
    client.init()

    responses = {'0010034602=?108': format_reply('000300'),  # get_turbo_motor_temperature()
                 '0010030902=?107': format_reply('000800'),  # get_turbo_actual_rotation_speed()
                 '0010030302=?101': format_reply('Err001'),  # get_turbo_error_code()
                 }
    emulator.define_responses(responses)

    resp = client.acq.start(test_mode=True, wait=0)
    resp = client.acq.wait()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
