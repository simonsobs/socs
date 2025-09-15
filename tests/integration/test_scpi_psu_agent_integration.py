import time

import ocs
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.base import OpCode
from ocs.testing import create_agent_runner_fixture, create_client_fixture

from socs.testing.device_emulator import create_device_emulator

wait_for_crossbar = create_crossbar_fixture()
run_agent = create_agent_runner_fixture(
    "../socs/agents/scpi_psu/agent.py",
    "scpi_psu_agent",
    args=["--log-dir", "./logs/"],
)
run_agent_acq = create_agent_runner_fixture(
    "../socs/agents/scpi_psu/agent.py",
    "scpi_psu_agent",
    args=["--log-dir", "./logs/",
          "--mode", "acq"],
)
client = create_client_fixture("psuK")
gpib_emu = create_device_emulator(
    {
        # manufacturer, model, serial, firmware
        "*idn?": "Keithley instruments, 2230G-30-1, 9203269, 1.16-1.04",
    },
    relay_type="tcp",
    port=1234,  # hard-coded in prologix_interface.py (line 16)
)


def check_resp_success(resp):
    print(resp)
    assert resp.status == ocs.OK
    print(resp.session)
    assert resp.session["op_code"] == OpCode.SUCCEEDED.value


@pytest.mark.integtest
def test_scpi_psu_init_psu(wait_for_crossbar, gpib_emu, run_agent, client):
    resp = client.init()
    check_resp_success(resp)


@pytest.mark.integtest
def test_scpi_psu_init_psu_acq_mode(wait_for_crossbar, gpib_emu, run_agent_acq, client):
    # Sleep to give time for the agent to initialize and enter the acq process
    time.sleep(2)
    resp = client.init.status()
    check_resp_success(resp)


@pytest.mark.integtest
def test_scpi_psu_set_output(wait_for_crossbar, gpib_emu, run_agent, client):
    client.init()
    resp = client.set_output(channel=2, state=True)
    check_resp_success(resp)

    resp = client.set_output(channel=2, state=False)
    check_resp_success(resp)


@pytest.mark.integtest
def test_scpi_psu_set_current(wait_for_crossbar, gpib_emu, run_agent, client):
    client.init()
    resp = client.set_current(channel=1, current=2.5)
    check_resp_success(resp)


@pytest.mark.integtest
def test_scpi_psu_set_voltage(wait_for_crossbar, gpib_emu, run_agent, client):
    client.init()
    resp = client.set_voltage(channel=3, volts=19.7)
    check_resp_success(resp)


@pytest.mark.integtest
def test_scpi_psu_monitor_output(wait_for_crossbar, gpib_emu, run_agent, client):
    responses = {
        "CHAN:OUTP:STAT?": "1",
        "MEAS:VOLT? CH1": "3.14",
        "MEAS:CURR? CH1": "6.28",
        "MEAS:VOLT? CH2": "2.72",
        "MEAS:CURR? CH2": "5.44",
        "MEAS:VOLT? CH3": "1.23",
        "MEAS:CURR? CH3": "2.46",
    }
    gpib_emu.define_responses(responses)

    client.init()
    resp = client.monitor_output.start(test_mode=True, wait=0)
    resp = client.monitor_output.wait()
    check_resp_success(resp)

    # stop process, else test hangs on auto-reconnection
    client.monitor_output.stop()
    client.monitor_output.wait()
