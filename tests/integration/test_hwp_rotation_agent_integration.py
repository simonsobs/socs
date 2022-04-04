import os
import time
import pytest
import signal
import subprocess
import coverage.data
import urllib.request

from urllib.error import URLError

from ocs.matched_client import MatchedClient

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
    '../agents/hwp_rotation/rotation_agent.py', 'hwp_rotation_agent', args=['--log-dir', './logs/'])
client = create_client_fixture('rotator')
kikusui_emu = create_device_emulator({'SYST:REM': ''}, relay_type='tcp', port=2000)  # kikusui
pid_emu = create_device_emulator({}, relay_type='telnet', port=2001)  # pid


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_hwp_rotation_tune_stop(wait_for_crossbar, kikusui_emu, pid_emu, run_agent, client):
    resp = client.tune_stop()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


# @pytest.mark.integtest
# def test_ls425_start_acq(wait_for_crossbar, emulator, run_agent, client):
#     responses = {'*IDN?': 'LSCI,MODEL425,LSA425T,1.3',
#                  'RDGFIELD?': '+1.0E-01'}
#     emulator.define_responses(responses)
# 
#     resp = client.acq.start(sampling_frequency=1.0)
#     assert resp.status == ocs.OK
#     assert resp.session['op_code'] == OpCode.STARTING.value
# 
#     # We stopped the process with run_once=True, but that will leave us in the
#     # RUNNING state
#     resp = client.acq.status()
#     assert resp.session['op_code'] == OpCode.RUNNING.value
# 
#     # Now we request a formal stop, which should put us in STOPPING
#     client.acq.stop()
#     # this is so we get through the acq loop and actually get a stop command in
#     # TODO: get sleep_time in the acq process to be small for testing
#     time.sleep(3)
#     resp = client.acq.status()
#     print(resp)
#     print(resp.session)
#     assert resp.session['op_code'] in [OpCode.STOPPING.value, OpCode.SUCCEEDED.value]
