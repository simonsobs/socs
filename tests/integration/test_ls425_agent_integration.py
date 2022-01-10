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
    agentproc = subprocess.Popen(['coverage', 'run',
                                  '--rcfile=./.coveragerc',
                                  '../agents/lakeshore425/LS425_agent.py',
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
def test_ls425_init_lakeshore(wait_for_crossbar, run_agent, client):
    resp = client.init_lakeshore()
    # print(resp)
    assert resp.status == ocs.OK
    # print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_ls425_start_acq(wait_for_crossbar, run_agent, client):
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
    resp = client.acq.status()
    assert resp.session['op_code'] == OpCode.STOPPING.value
