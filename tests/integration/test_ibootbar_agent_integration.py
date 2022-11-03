import pytest
from multiprocessing import Process
import signal
import os
import subprocess
from unittest.mock import patch
from twisted.internet.defer import inlineCallbacks
from snmpsim.commands import responder

import ocs
from ocs.base import OpCode
from socs.snmp import SNMPTwister

from ocs.testing import (
    create_agent_runner_fixture,
    create_client_fixture,
)

from integration.util import create_crossbar_fixture

pytest_plugins = "docker_compose"

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../agents/ibootbar/ibootbar.py",
    "ibootbarAgent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("ibootbar")

subprocess.run(
    "mkdir -p ~/.pysnmp/mibs && cp -r ../agents/ibootbar/mibs/. ~/.pysnmp/mibs",
    shell=True,
)

address = "127.0.0.1"
port = 1024


def check_resp_success(resp):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.fixture
def start_responder():
    with patch(
        "sys.argv",
        [
            "test_ibootbar_agent_integration.py",
            "--data-dir=./integration/ibootbar_snmp_data",
            f"--agent-udpv4-endpoint={address}:{port}",
            # f"--variation-modules-dir={os.path.expanduser('~/.local/share/snmpsim/variation')}",
        ],
    ):
        p = Process(target=responder.main)
        p.start()
        yield
        os.kill(p.pid, signal.SIGINT)


@pytest.mark.integtest
def test_ibootbar_acq(wait_for_crossbar, start_responder, run_agent, client):
    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()
    check_resp_success(resp)


@pytest.mark.integtest
@inlineCallbacks
def test_ibootbar_set_outlet(wait_for_crossbar, start_responder, run_agent, client):
    outlet_number = 3
    resp = client.set_outlet(outlet=outlet_number, state="on")
    check_resp_success(resp)

    # Simulate internal state transition of hardware
    snmp = SNMPTwister(address, port)
    outlet = [("IBOOTPDU-MIB", "outletStatus", outlet_number - 1)]
    yield snmp.set(oid_list=outlet, version=2, setvalue=1, community_name="public")

    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()

    assert resp.session["data"][f"outletStatus_{outlet_number - 1}"]["status"] == 1


@pytest.mark.integtest
def test_ibootbar_set_initial_state(
        wait_for_crossbar, start_responder, run_agent, client):
    resp = client.set_initial_state()
    check_resp_success(resp)


@pytest.mark.integtest
def test_ibootbar_cycle_outlet(wait_for_crossbar, start_responder, run_agent, client):
    resp = client.cycle_outlet(outlet=7, cycle_time=5)
    check_resp_success(resp)
