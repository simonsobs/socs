import time
import pytest

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
    "../agents/sorenson_dlm/dlm_agent.py",
    "dlm_agent",
    args=["--log-dir", "./logs/"],
)
client = create_client_fixture("dlm")
emu = create_device_emulator({"hello": "world"}, relay_type="tcp", port=9221)


@pytest.mark.integtest
def test_dlm_init(wait_for_crossbar, emu, run_agent, client):
    resp = client.init_dlm(force=True)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_dlm_acq(wait_for_crossbar, emu, run_agent, client):
    responses = {"SOUR:VOLT?;OPC?": "15", "MEAS:CURR?;OPC?": "1.85"}
    emu.define_responses(responses)

    resp = client.acq.start()
    assert resp.status == ocs.OK
    assert resp.session["op_code"] == OpCode.STARTING.value
    time.sleep(1)
    resp = client.acq.status()
    assert resp.status == ocs.OK
    assert resp.session["op_code"] == OpCode.RUNNING.value

    client.acq.stop()
    time.sleep(1)  # can implement a 'run_once' param for testing later
    resp = client.acq.status()
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] in [OpCode.STOPPING.value, OpCode.SUCCEEDED.value]


@pytest.mark.integtest
def test_dlm_set_over_volt(wait_for_crossbar, emu, run_agent, client):
    responses = {
        "SOUR:VOLT:PROT?;OPC?": "25.5",
        "STAT:PROT:ENABLE?;OPC?": "8",
        "STAT:PROT:EVENT?;OPC?": "0",
    }
    emu.define_responses(responses)

    resp = client.set_over_volt(over_volt=25.5)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_dlm_set_voltage(wait_for_crossbar, emu, run_agent, client):
    responses = {
        "SOUR:VOLT:PROT?;OPC?": "120",
        "STAT:PROT:ENABLE?;OPC?": "8",
        "STAT:PROT:EVENT?;OPC?": "0",
    }
    emu.define_responses(responses)

    resp = client.set_over_volt(over_volt=120)
    resp = client.set_voltage(voltage=75.8)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_dlm_trigger_over_volt(wait_for_crossbar, emu, run_agent, client):
    responses = {
        "SOUR:VOLT:PROT?;OPC?": "13.5",
        "STAT:PROT:ENABLE?;OPC?": "8",
        "STAT:PROT:EVENT?;OPC?": "0",
    }
    emu.define_responses(responses)

    resp = client.set_over_volt(over_volt=13.5)
    resp = client.set_voltage(voltage=23.2)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.FAILED.value


@pytest.mark.integtest
def test_dlm_set_current(wait_for_crossbar, emu, run_agent, client):
    responses = {
        "SOUR:VOLT:PROT?;OPC?": "50",
        "STAT:PROT:ENABLE?;OPC?": "8",
        "STAT:PROT:EVENT?;OPC?": "0",
    }
    emu.define_responses(responses)

    resp = client.set_over_volt(over_volt=50)
    resp = client.set_current(current=1.35)
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value
