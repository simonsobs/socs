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

from integration.util import (
    create_agent_runner_fixture,
    create_client_fixture,
    create_crossbar_fixture
)

from integration.responder import create_responder_fixture

pytest_plugins = ("docker_compose")

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../agents/lakeshore425/LS425_agent.py', 'ls425_agent')
client = create_client_fixture('LS425')
responder = create_responder_fixture({'*IDN?': 'LSCI,MODEL425,4250022,1.0'})


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_ls425_init_lakeshore(wait_for_crossbar, responder, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls425_start_acq(wait_for_crossbar, responder, run_agent, client):
    responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
                 'RDGFIELD?': '+1.0E-01'}
    responder.define_responses(responses)

    client.init_lakeshore()
    resp = client.acq.start(sample_heater=False, run_once=True)
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


# testing the new responder fixture
@pytest.mark.integtest
def test_ls425_generic_responder_demo(wait_for_crossbar, responder, run_agent, client):
    # Setup so that you get this/these response(s) from the command(s)
    responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
                 'RDGFIELD?': '+1.0E-01'}
    responder.define_responses(responses)

    resp = client.init_lakeshore()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value

    resp = client.acq.start()
    # give time for data to collect
    time.sleep(5)
    resp = client.acq.status()
    print(resp)
    print(resp.session)
