import pytest
from multiprocessing import Process
import signal
import os
import time
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
    "../agents/ups/ups.py",
    "UPSAgent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("ups")

subprocess.run(
    "mkdir -p ~/.pysnmp/mibs && cp -r ../agents/ups/mibs/. ~/.pysnmp/mibs",
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
            "test_ups_agent_integration.py",
            "--data-dir=./integration/ups_snmp_data",
            f"--agent-udpv4-endpoint={address}:{port}",
            # f"--variation-modules-dir={os.path.expanduser('~/.local/share/snmpsim/variation')}",
        ],
    ):
        p = Process(target=responder.main)
        p.start()
        yield
        os.kill(p.pid, signal.SIGINT)


@pytest.mark.integtest
def test_ups_acq(wait_for_crossbar, start_responder, run_agent, client):
    resp = client.acq.start(test_mode=True)
    resp = client.acq.wait()
    check_resp_success(resp)
