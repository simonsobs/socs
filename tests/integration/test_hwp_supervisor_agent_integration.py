import signal
import subprocess
from pprint import pprint
from typing import Any, Dict, Generator

import coverage.data
import pytest
from integration.util import docker_compose_file  # noqa: F401
from integration.util import create_crossbar_fixture
from ocs.testing import SIGINT_TIMEOUT, _AgentRunner, create_client_fixture

from socs.testing.hwp_emulator import HWPEmulator

log_dir = "./logs/"

pid_client = create_client_fixture("hwp-pid")
sup_client = create_client_fixture("hwp-supervisor")
pcu_client = create_client_fixture("hwp-pcu")
gripper_client = create_client_fixture("hwp-gripper")
wait_for_crossbar = create_crossbar_fixture()


@pytest.fixture()
def hwp_em() -> Generator[HWPEmulator, None, None]:
    em = HWPEmulator(pid_port=0, pmx_port=0, enc_port=0)
    em.start()
    yield em
    em.shutdown()


def _shutdown_agent_runner(runner: _AgentRunner) -> None:
    """
    Shutdown the agent process using SIGKILL.
    """
    # don't send SIGINT if we've already sent SIGKILL
    if not runner._timedout:
        runner.proc.send_signal(signal.SIGKILL)
    runner._timer.cancel()

    try:
        runner.proc.communicate(timeout=SIGINT_TIMEOUT)
    except subprocess.TimeoutExpired:
        runner._raise_subprocess(
            "Agent did not terminate within " f"{SIGINT_TIMEOUT} seconds on SIGINT."
        )

    if runner._timedout:
        stdout, stderr = runner.proc.communicate(timeout=SIGINT_TIMEOUT)
        print(f"Here is stdout from {runner.agent_name}:\n{stdout}")
        print(f"Here is stderr from {runner.agent_name}:\n{stderr}")
        raise RuntimeError("Agent timed out.")


def _cleanup_runner(runner: _AgentRunner, cov) -> None:
    _shutdown_agent_runner(runner)
    # report coverage
    agentcov = coverage.data.CoverageData(
        basename=f".coverage.agent.{runner.agent_name}"
    )
    agentcov.read()
    # protect against missing --cov flag
    if cov is not None:
        cov.get_data().update(agentcov)


@pytest.fixture()
def pid_agent(
    wait_for_crossbar, hwp_em: HWPEmulator, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_pid/agent.py"
    agent_name = "pid"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
        "--port",
        str(hwp_em.pid_device.socket_port),
        "--instance-id",
        "hwp-pid",
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


@pytest.fixture()
def encoder_agent(
    wait_for_crossbar, hwp_em: HWPEmulator, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_encoder/agent.py"
    agent_name = "pid"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
        "--port",
        str(hwp_em.enc_port),
        "--instance-id",
        "hwp-enc",
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


@pytest.fixture()
def pmx_agent(
    wait_for_crossbar, hwp_em: HWPEmulator, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_pmx/agent.py"
    agent_name = "pmx"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
        "--port",
        str(hwp_em.pmx_device.socket_port),
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


@pytest.fixture()
def pcu_agent(
    wait_for_crossbar, hwp_em: HWPEmulator, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_pcu/agent.py"
    agent_name = "pcu"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
        "--port",
        "./responder",
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


@pytest.fixture()
def gripper_agent(
    wait_for_crossbar, hwp_em: HWPEmulator, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_gripper/agent.py"
    agent_name = "gripper"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
        "--control-port",
        str(hwp_em.gripper_device.socket_port),
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


@pytest.fixture()
def supervisor_agent(
    pid_agent, pmx_agent, pcu_agent, encoder_agent, gripper_agent, cov
) -> Generator[None, None, None]:
    agent_path = "../socs/agents/hwp_supervisor/agent.py"
    agent_name = "supervisor"
    timeout = 60
    args = [
        "--log-dir",
        log_dir,
    ]
    runner = _AgentRunner(agent_path, agent_name, args)
    runner.run(timeout=timeout)
    yield
    _cleanup_runner(runner, cov)


def get_hwp_state(client) -> Dict[str, Any]:
    return client.query_hwp_state().session["data"]["state"]


def test_supervisor_grip(hwp_em, supervisor_agent, sup_client) -> None:
    state = get_hwp_state(sup_client)
    pprint(state)
    assert state["gripper"]["grip_state"] == "ungripped"
    sup_client.grip_hwp()
    state = get_hwp_state(sup_client)
    assert state["gripper"]["grip_state"] == "warm"


def test_hwp_spinup(supervisor_agent, sup_client) -> None:
    assert not get_hwp_state(sup_client)["is_spinning"]
    sup_client.pid_to_freq(target_freq=2.0)
    assert get_hwp_state(sup_client)["is_spinning"]
    status = sup_client.pid_to_freq.status()
    pprint(status.session["data"])
