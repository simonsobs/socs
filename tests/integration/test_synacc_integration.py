import pytest
from http_server_mock import HttpServerMock
from flask import request

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
    "../agents/synacc/synacc.py",
    "synacc",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("synacc")


@pytest.fixture
def app():
    return HttpServerMock(__name__)


@pytest.fixture
def ctx(app):
    return app.run("localhost", 5000)


def check_resp_state(resp, opcode=OpCode.SUCCEEDED.value):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == opcode


@pytest.mark.integtest
def test_synacc_startup(wait_for_crossbar, app, ctx, run_agent, client):
    @app.route("/cmd.cgi", methods=["GET"])
    def status():
        query = request.query_string.decode()
        print("query:", query)
        assert query == "$A5"
        return "$A0,00101"

    with ctx:
        resp = client.get_status.wait()  # get_status runs on startup
        check_resp_state(resp)
        resp = client.status_acq.status()
        check_resp_state(resp, OpCode.RUNNING.value)


@pytest.mark.integtest
def test_synacc_reboot(wait_for_crossbar, app, ctx, run_agent, client):
    @app.route("/cmd.cgi", methods=["GET"])
    def reboot():
        query = request.query_string.decode()
        print("query:", query)
        assert query == "$A4%203"
        return ""

    with ctx:
        resp = client.reboot(outlet=3)
        check_resp_state(resp)


@pytest.mark.integtest
def test_synacc_set_outlet(wait_for_crossbar, app, ctx, run_agent, client):
    @app.route("/cmd.cgi", methods=["GET"])
    def status():
        query = request.query_string.decode()
        print("query:", query)
        assert query == "$A3%204%201"
        return ""

    with ctx:
        resp = client.set_outlet(outlet=4, on=True)
        check_resp_state(resp)


@pytest.mark.integtest
def test_synacc_set_all(wait_for_crossbar, app, ctx, run_agent, client):
    @app.route("/cmd.cgi", methods=["GET"])
    def status():
        query = request.query_string.decode()
        print("query:", query)
        assert query == "$A7%201"
        return ""

    with ctx:
        resp = client.set_all(on=True)
        check_resp_state(resp)
