import pytest
from http_server_mock import HttpServerMock
import requests
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


def check_resp_success(resp):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_synacc_start(wait_for_crossbar, app, ctx, run_agent, client):
    @app.route("/", methods=["GET"])
    def index():
        return "Hello world"

    @app.route("/cmd.cgi", methods=["GET"])
    def status():
        print("query string:", request.query_string)
        return "Bye world"

    with ctx:
        r = requests.get("http://admin:admin@127.0.0.1:5000/cmd.cgi?$A5")
        assert r.status_code == 200
        assert r.text == "Bye world"

        # resp = client.get_status()
        # check_resp_success(resp)
