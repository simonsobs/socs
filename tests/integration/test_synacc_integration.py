import ocs
import pytest
from flask import request
from http_server_mock import HttpServerMock
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../socs/agents/synacc/agent.py",
    "synacc",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("synacc")


@pytest.fixture
def http_mock():
    app = HttpServerMock(__name__)

    @app.route("/cmd.cgi", methods=["GET"])
    def route_fn():
        query = request.query_string.decode()
        print("query:", query)
        # test_synacc_startup
        if query == "$A5":
            return "$A0,00101"
        # test_synacc_reboot
        elif query == "$A4%203":
            return ""
        # test_synacc_set_outlet_on (recall that %20 is a space)
        elif query == "$A3%204%201":
            return ""
        # test_synacc_set_outlet_off (recall that %20 is a space)
        elif query == "$A3%203%200":
            return ""
        # test_synacc_set_all
        elif query == "$A7%201":
            return ""
        else:
            assert False, "Bad query"

    return app.run("localhost", 8000)


def check_resp_state(resp, opcode=OpCode.SUCCEEDED.value):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == opcode


@pytest.mark.integtest
def test_synacc_startup(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.get_status.wait()  # get_status runs on startup
        check_resp_state(resp)
        resp = client.status_acq.status()
        check_resp_state(resp, OpCode.RUNNING.value)


@pytest.mark.integtest
def test_synacc_reboot(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.reboot(outlet=3)
        check_resp_state(resp)


@pytest.mark.integtest
def test_synacc_set_outlet_on(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.set_outlet(outlet=4, on=True)
        check_resp_state(resp)


@pytest.mark.integtest
def test_synacc_set_outlet_off(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.set_outlet(outlet=3, on=False)
        check_resp_state(resp)


@pytest.mark.integtest
def test_synacc_set_all(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.set_all(on=True)
        check_resp_state(resp)
