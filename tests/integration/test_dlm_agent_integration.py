import pytest

import ocs
from ocs.base import OpCode

from ocs.testing import (
    create_agent_runner_fixture,
    create_client_fixture,
)

from integration.util import create_crossbar_fixture

from socs.testing.device_emulator import create_device_emulator

pytest_plugins = "docker_compose"

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../agents/sorenson_dlm/dlm_agent.py",
    "dlm_agent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("dlm")  # not defined yet
emu = create_device_emulator({"hello": "world"}, relay_type="tcp", port=9221)


@pytest.mark.integtest
def test_testing(wait_for_crossbar):
    """Just a quick test to make sure we can bring up crossbar."""
    assert True
