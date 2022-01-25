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

pytest_plugins = ("docker_compose")

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()


# Fixture to wait for crossbar server to be available.
# Speeds up tests a bit to have this session scoped
# If tests start interfering with one another this should be changed to
# "function" scoped and session_scoped_container_getter should be changed to
# function_scoped_container_getter
@pytest.fixture(scope="session")
def wait_for_crossbar(session_scoped_container_getter):
    """Wait for the crossbar server from docker-compose to become
    responsive.

    """
    attempts = 0

    while attempts < 6:
        try:
            code = urllib.request.urlopen("http://localhost:18001/info").getcode()
        except (URLError, ConnectionResetError):
            print("Crossbar server not online yet, waiting 5 seconds.")
            time.sleep(5)

        attempts += 1

    assert code == 200
    print("Crossbar server online.")


@pytest.fixture()
def run_agent(cov):
    env = os.environ.copy()
    env['COVERAGE_FILE'] = '.coverage.agent'
    env['OCS_CONFIG_DIR'] = os.getcwd()
    agentproc = subprocess.Popen(['coverage', 'run',
                                  '--rcfile=./.coveragerc',
                                  '../agents/lakeshore372/LS372_agent.py',
                                  '--site-file',
                                  './default.yaml'],
                                 env=env,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 preexec_fn=os.setsid)

    # wait for Agent to connect
    time.sleep(1)

    yield

    # shutdown Agent
    agentproc.send_signal(signal.SIGINT)
    time.sleep(1)

    # report coverage
    agentcov = coverage.data.CoverageData(basename='.coverage.agent')
    agentcov.read()
    cov.get_data().update(agentcov)


@pytest.fixture()
def client():
    client = MatchedClient('LSASIM')
    return client


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True


@pytest.mark.integtest
def test_ls372_init_lakeshore(wait_for_crossbar, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_enable_control_chan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.enable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_disable_control_chan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.disable_control_chan()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_start_acq(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.acq.start(sample_heater=False, run_once=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.STARTING.value

    resp = client.acq.status()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_range(range=1e-3, heater='sample', wait=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation_mode(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation_mode(channel=1, mode='current')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_excitation(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_excitation(channel=1, value=1e-9)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_excitation(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_excitation(channel=1, value=1e-9)
    resp = client.get_excitation(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['excitation'] == 1e-9


@pytest.mark.integtest
def test_ls372_set_resistance_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_resistance_range(channel=1, resistance_range=2)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_resistance_range(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_resistance_range(channel=1, resistance_range=2)
    resp = client.get_resistance_range(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['resistance_range'] == 2


@pytest.mark.integtest
def test_ls372_set_dwell(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_dwell(channel=1, dwell=3)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_dwell(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    client.set_dwell(channel=1, dwell=3)
    resp = client.get_dwell(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
    assert resp.session['data']['dwell_time'] == 3


@pytest.mark.integtest
def test_ls372_set_pid(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_pid(P=40, I=2, D=0)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_active_channel(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_active_channel(channel=1)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_autoscan(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_autoscan(autoscan=True)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_output_mode(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_output_mode(heater='still', mode='Off')
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_heater_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_heater_output(heater='still', output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_set_still_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.set_still_output(output=50)
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls372_get_still_output(wait_for_crossbar, run_agent, client):
    client.init_lakeshore()
    resp = client.get_still_output()
    assert resp.status == ocs.OK
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
