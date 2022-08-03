import pytest
from multiprocessing import Process
import time
from unittest.mock import patch
from snmpsim.commands import responder

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
    "../agents/ibootbar/ibootbar.py",
    "ibootbar_agent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("ibootbar")


def check_resp_success(resp):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.fixture
def start_responder():
    def f():
        with patch(
            "sys.argv",
            [
                "test_ibootbar_agent_integration.py",
                "--data-dir=./integration/ibootbar_snmp_data",
                "--agent-udpv4-endpoint=127.0.0.1:1024",
                # "--variation-modules-dir=???/.local/share/snmpsim/variation"
            ],
        ):
            responder.main()

    p = Process(target=f)
    p.start()
    yield
    p.terminate()


@pytest.mark.integtest
def test_ibootbar_acq(wait_for_crossbar, start_responder, run_agent, client):
    time.sleep(5)
    client.acq.stop()
    time.sleep(1)
    resp = client.acq.status()
    check_resp_success(resp)


@pytest.mark.integtest
def test_ibootbar_set_outlet(wait_for_crossbar, start_responder, run_agent, client):
    resp = client.set_outlet(outlet=3, state="on")
    check_resp_success(resp)


@pytest.mark.integtest
def test_ibootbar_cycle_outlet(wait_for_crossbar, start_responder, run_agent, client):
    resp = client.cycle_outlet(outlet=5, cycle_time=5)
    check_resp_success(resp)
