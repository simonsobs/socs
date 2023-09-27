import os

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.bluefors_simulator import create_bluefors_simulator

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    '../socs/agents/bluefors/agent.py',
    'bluefors_agent',
    args=["--log-dir", "./logs/"])
client = create_client_fixture('bluefors')
simulator = create_bluefors_simulator()


@pytest.mark.integtest
def test_bluefors_acq(wait_for_crossbar, simulator, run_agent, client):
    client.acq.stop()

    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()

    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session['op_code'] == OpCode.SUCCEEDED.value
