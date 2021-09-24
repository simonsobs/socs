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

pytest_plugins = ("docker_compose")

# Fixture to wait for crossbar server to be available.
# Speeds up tests a bit to have this session scoped
# If tests start interfering with one another this should be changed to "function" scoped
# and session_scoped_container_getter should be changed to function_scoped_container_getter
@pytest.fixture(scope="session")
def wait_for_crossbar(session_scoped_container_getter):
    """Wait for the crossbar server from docker-compose to become responsive."""
    attempts = 0

    while attempts < 6:
        try:
            code = urllib.request.urlopen("http://localhost:8001/info").getcode()
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
    agentproc = subprocess.Popen(['coverage', 'run', '--rcfile=./.coveragerc', '../agents/lakeshore372/LS372_agent.py', '--site-file', './default.yaml'],
                                 env=env,
                                 stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE,
                                 preexec_fn=os.setsid)

    # wait for Agent to connect
    time.sleep(2)

    yield

    agentproc.send_signal(signal.SIGINT)
    time.sleep(1)
    # 4.
    agentcov = coverage.data.CoverageData(basename='.coverage.agent')
    agentcov.read()
    cov.get_data().update(agentcov)

@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True

@pytest.mark.integtest
def test_init_lakeshore(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    #print(os.getenv('OCS_CONFIG_DIR'))
    client = MatchedClient('LSASIM')
    resp = client.init_lakeshore()
    #print(resp)
    assert resp.status == ocs.OK
    #print(resp.session)

@pytest.mark.integtest
def test_enable_control_chan(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.enable_control_chan()
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_disable_control_chan(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.disable_control_chan()
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_start_acq(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.acq.start(sample_heater=False, run_once=True)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_heater_range(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_heater_range(range=1e-3, heater='sample', wait=0)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_excitation_mode(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_excitation_mode(channel=1, mode='current')
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_excitation(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_excitation(channel=1, value=1e-9)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_pid(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_pid(P=40, I=2, D=0)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_active_channel(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_active_channel(channel=1)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_autoscan(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_autoscan(autoscan=True)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_output_mode(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_output_mode(heater='still', mode='Off')
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_heater_output(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_heater_output(heater='still', output=50)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_set_still_output(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.set_still_output(output=50)
    assert resp.status == ocs.OK

@pytest.mark.integtest
def test_get_still_output(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    client = MatchedClient('LSASIM')
    client.init_lakeshore()
    resp = client.get_still_output()
    assert resp.status == ocs.OK
