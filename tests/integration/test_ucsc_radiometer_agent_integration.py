import time
from datetime import datetime

import ocs
import pytest
from flask import jsonify, request
from http_server_mock import HttpServerMock
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../socs/agents/ucsc_radiometer/agent.py",
    "radiometer",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("pwvs")


@pytest.fixture
def http_mock():
    app = HttpServerMock(__name__)

    @app.route("/", methods=["GET"])
    def route_fn():
        if request.method == "GET":
            time_now = datetime.now()
            timestamp = time.mktime(time_now.timetuple())
            data = {'pwv': 1.2, 'timestamp': timestamp}
            return jsonify(data)
        else:
            assert False, "Bad query"

    return app.run("127.0.0.1", 5000)


@pytest.mark.integtest
def test_ucsc_radiometer_acq(wait_for_crossbar, http_mock, run_agent, client):
    with http_mock:
        resp = client.acq.start(test_mode=True)
        resp = client.acq.wait()
        print(resp)
        assert resp.status == ocs.OK
        print(resp.session)
        assert resp.session['op_code'] == OpCode.SUCCEEDED.value
