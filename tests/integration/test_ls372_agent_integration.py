import os
import time
import pytest
import signal
import subprocess
import coverage.data
import urllib.request

from urllib.error import URLError

from ocs.matched_client import MatchedClient

pytest_plugins = ("docker_compose")

# Fixture to wait for crossbar server to be available.
@pytest.fixture(scope="function")
def wait_for_crossbar(function_scoped_container_getter):
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

    # wait for Agent to initialize (can we make this faster?)
    time.sleep(10)

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
def test_agent(wait_for_crossbar, run_agent):
    os.environ['OCS_CONFIG_DIR'] = os.getcwd()
    print(os.getenv('OCS_CONFIG_DIR'))
    client = MatchedClient('LSASIM')
    resp = client.init_lakeshore()
    print(resp)
