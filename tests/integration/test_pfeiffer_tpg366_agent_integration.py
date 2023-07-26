import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../socs/agents/pfeiffer_tpg366/agent.py",
    "pfeiffer_tpg366_agent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("pfeiffer366")
# correct responses found here (page 11):
# https://www.ajvs.com/library/TPG_366_Communication_Protocol_BG5511BEN.pdf
emu = create_device_emulator(
    {
        "PRX": "\x06\r\n",
        "\x05": "0,+1.2345E+01,0,+2.3456E+01,0,+3.4567E+01,0,+4.5678E+01,0,+5.6789E+01,0,+6.7891E+01\r\n",
    },
    relay_type="tcp",
    port=8000,
)


def check_resp_success(resp):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_pfeiffer_tpg366_acq(wait_for_crossbar, emu, run_agent, client):
    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()
    check_resp_success(resp)
