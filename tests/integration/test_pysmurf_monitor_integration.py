import json
import os
import shutil
import socket
import time

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

TMPFILE = '/tmp/pytest-socs/suprsync.db'

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../socs/agents/pysmurf_monitor/agent.py",
    "pysmurf_monitor",
    args=["--log-dir", "./logs/",
          "--db-path", TMPFILE],
)
client = create_client_fixture("pysmurf-monitor")


@pytest.fixture
def cleanup():
    """Clean up temp database file."""
    yield
    dir_ = os.path.dirname(TMPFILE)
    shutil.rmtree(dir_)


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


def write_test_file(path):
    full_path = os.path.join(path, 'test_data.txt')

    # Could be made more realistic if needed
    with open(full_path, 'w', encoding='utf-8') as f:
        f.write("3.1415\n")

    return full_path


@pytest.mark.integtest
def test_pysmurf_monitor_run_data_file(wait_for_crossbar, publisher, run_agent, client,
                                       cleanup, tmp_path):
    test_file = write_test_file(tmp_path)
    file_data = {
        "path": test_file,
        "type": "testing",
        "format": "txt",
        "timestamp": time.time(),
        "action": None,
        "action_ts": None,
        "plot": False,
        "pysmurf_version": "v0.7.0",
    }
    publisher(file_data, "data_file")
    client.run.start(test_mode=True)
    client.run.wait()
    check_resp(client.run.status())


@pytest.mark.integtest
def test_pysmurf_monitor_run_session_log(wait_for_crossbar, publisher, run_agent, client, cleanup):
    log_message = "This is a test log message"
    publisher(log_message, "session_log")
    client.run.start(test_mode=True)
    client.run.wait()
    check_resp(client.run.status())


@pytest.mark.integtest
def test_pysmurf_monitor_run_metadata(wait_for_crossbar, publisher, run_agent, client,
                                      cleanup, tmp_path):
    test_file = write_test_file(tmp_path)
    file_data = {
        "path": test_file,
        "value": 1,
        "type": "testing",
    }
    publisher(file_data, "metadata")
    client.run.start(test_mode=True)
    client.run.wait()
    check_resp(client.run.status())
