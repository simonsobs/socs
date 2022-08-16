import pytest
import socket
import time
import json

import ocs
from ocs.base import OpCode

from ocs.testing import (
    create_agent_runner_fixture,
    create_client_fixture,
)

from integration.util import create_crossbar_fixture

pytest_plugins = "docker_compose"

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../agents/pysmurf_monitor/pysmurf_monitor.py",
    "pysmurf_monitor",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("pysmurf-monitor")


@pytest.fixture
def publisher():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    UDP_MAX_BYTES = 64000
    seq_no = 0

    def udp_send(json_msg):
        payload = bytes(json_msg, "utf_8")
        if len(payload) > UDP_MAX_BYTES:
            # Can't send this; write to stderr and notify consumer.
            error = f"Backend error: dropped large UDP packet ({len(payload)} bytes)."
            assert False, error
        sock.sendto(payload, ("localhost", 8200))

    def publish(data, msgtype="general"):
        nonlocal seq_no
        # Create the wrapper.
        output = {
            "host": socket.gethostname(),
            "id": "testing",
            "script": "test_pysmurf_monitor_integration",
            "time": time.time(),
            "seq_no": seq_no,
            "type": msgtype,
        }
        seq_no += 1
        # Add in the data and convert to json.
        output["payload"] = data
        jtext = json.dumps(output)
        # Send.
        udp_send(jtext)

    return publish


def check_resp(resp, opcode=OpCode.SUCCEEDED):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == opcode.value


@pytest.mark.integtest
def test_pysmurf_monitor_run(wait_for_crossbar, publisher, run_agent, client):
    file_data = {
        "path": "./integration/pysmurf_monitor_data/test_data.txt",
        "type": "testing",
        "format": "txt",
        "timestamp": None,
        "action": None,
        "action_ts": None,
        "plot": False,
        "pysmurf_version": None,
    }
    publisher(file_data, "data_file")
    time.sleep(2)
