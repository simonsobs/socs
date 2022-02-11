import time
import pytest

import ocs
from ocs.base import OpCode

from ocs.testing import (
    create_agent_runner_fixture,
    create_client_fixture,
)

from integration.util import (
    create_crossbar_fixture
)

from socs.testing.device_emulator import create_device_emulator

pytest_plugins = ("docker_compose")

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../agents/pfeiffer_tc400/pfeiffer_tc400_agent.py', 'tc400_agent', args=['--log-dir', './logs'])
client = create_client_fixture('pfeifferturboA')
emulator = create_device_emulator({}, relay_type='tcp')


@pytest.mark.integtest
def test_pfeiffer_tc400_init_lakeshore(wait_for_crossbar, emulator, run_agent, client):
    resp = client.init()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


#@pytest.mark.integtest
#def test_pfeiffer_tc400_start_acq(wait_for_crossbar, emulator, run_agent, client):
#    client.init_lakeshore()
#
#    responses = {'*IDN?': 'LSCI,MODEL240,LSA240S,1.3',
#                 'KRDG? 1': '+1.0E-03',
#                 'SRDG? 1': '+1.0E+03',
#                 'KRDG? 2': '+1.0E-03',
#                 'SRDG? 2': '+1.0E+03',
#                 'KRDG? 3': '+1.0E-03',
#                 'SRDG? 3': '+1.0E+03',
#                 'KRDG? 4': '+1.0E-03',
#                 'SRDG? 4': '+1.0E+03',
#                 'KRDG? 5': '+1.0E-03',
#                 'SRDG? 5': '+1.0E+03',
#                 'KRDG? 6': '+1.0E-03',
#                 'SRDG? 6': '+1.0E+03',
#                 'KRDG? 7': '+1.0E-03',
#                 'SRDG? 7': '+1.0E+03',
#                 'KRDG? 8': '+1.0E-03',
#                 'SRDG? 8': '+1.0E+03'}
#    emulator.define_responses(responses)
#
#    resp = client.acq.start(sampling_frequency=1.0)
#    assert resp.status == ocs.OK
#    assert resp.session['op_code'] == OpCode.STARTING.value
#
#    # We stopped the process with run_once=True, but that will leave us in the
#    # RUNNING state
#    resp = client.acq.status()
#    assert resp.session['op_code'] == OpCode.RUNNING.value
#
#    # Now we request a formal stop, which should put us in STOPPING
#    client.acq.stop()
#    # this is so we get through the acq loop and actually get a stop command in
#    # TODO: get sleep_time in the acq process to be small for testing
#    time.sleep(3)
#    resp = client.acq.status()
#    print(resp)
#    print(resp.session)
#    assert resp.session['op_code'] in [OpCode.STOPPING.value,
#                                       OpCode.SUCCEEDED.value]


@pytest.mark.integtest
def test_pfeiffer_tc400_turn_turbo_on(wait_for_crossbar, emulator, run_agent, client):
    client.init()

    #responses = {'001 10 010 06 111111 015': '00110'}
    responses = {'0011001006111111015': '0011001006111111015\r',  # ready_turbo()
                 '0011002306111111019': '0011001006111111015\r',  # turn_turbo_motor_on()
    }
    emulator.define_responses(responses)

    resp = client.turn_turbo_on()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
