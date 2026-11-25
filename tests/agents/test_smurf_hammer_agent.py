import os
import tempfile
import threading
import time
from unittest import mock

import pytest
import zmq

# jackhammer reads sys_config.yml from SMURF_CONFIG_DIR at import time
_cfg_dir = tempfile.mkdtemp()
with open(os.path.join(_cfg_dir, 'sys_config.yml'), 'w') as f:
    f.write('slot_order: [2, 3, 5]\n')
os.environ['SMURF_CONFIG_DIR'] = _cfg_dir

from socs.agents.smurf_hammer.agent import (CONFIGURED_REG, CONFIGURING_REG,
                                            SmurfHammerAgent, read_register,
                                            read_registers, server_port)


class FakeRogueServer:
    """Answer rogue-style pickled ZMQ requests on ``base_port + 1``.

    ``values`` maps a register path to the pickled reply object. Paths not
    in the map are answered with None, as rogue does for an unknown node.
    """

    def __init__(self, values):
        self.values = values
        self.requests = []
        self.ctx = zmq.Context()
        self.sock = self.ctx.socket(zmq.REP)
        self.base_port = self.sock.bind_to_random_port('tcp://127.0.0.1') - 1
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                req = self.sock.recv_pyobj()
            except zmq.ZMQError:
                return
            self.requests.append(req)
            self.sock.send_pyobj(self.values.get(req['path']))

    def close(self):
        self.sock.close(linger=0)
        self.ctx.term()
        self.thread.join(timeout=2)


@pytest.fixture
def fake_server():
    srv = FakeRogueServer({
        CONFIGURED_REG: True,
        CONFIGURING_REG: False,
        'AMCc.Broken': Exception("pyrogue.VariableError: boom"),
    })
    yield srv
    srv.close()


def test_server_port():
    assert server_port(2) == 9006
    assert server_port('5') == 9015


def test_read_register_values(fake_server):
    assert read_register(fake_server.base_port, CONFIGURED_REG) is True
    assert read_register(fake_server.base_port, CONFIGURING_REG) is False
    # the request is in rogue's ZmqServer format
    assert fake_server.requests[-1] == {
        'path': CONFIGURING_REG, 'attr': 'get', 'args': [], 'kwargs': {}}


def test_read_register_unknown_node_and_error(fake_server):
    assert read_register(fake_server.base_port, 'AMCc.DoesNotExist') is None
    assert read_register(fake_server.base_port, 'AMCc.Broken') is None


def _dead_ports(n):
    """Base ports whose request socket (port + 1) has nothing listening."""
    ctx = zmq.Context()
    ports = []
    for _ in range(n):
        s = ctx.socket(zmq.REP)
        ports.append(s.bind_to_random_port('tcp://127.0.0.1') - 1)
        s.close(linger=0)
    ctx.term()
    return ports


def test_read_register_timeout():
    # nothing listens on this port; the reply must time out, not hang
    (port,) = _dead_ports(1)
    assert read_register(port, CONFIGURED_REG, timeout=0.2) is None


def test_read_registers_concurrent_timeouts():
    """Six unreachable slots, two registers each, cost one timeout."""
    requests = [(port, reg) for port in _dead_ports(6)
                for reg in (CONFIGURED_REG, CONFIGURING_REG)]
    timeout = 0.5
    t0 = time.monotonic()
    values = read_registers(requests, timeout=timeout)
    elapsed = time.monotonic() - t0
    assert values == [None] * 12
    assert elapsed < 2 * timeout, f"took {elapsed:.2f}s for 12 requests"


def test_read_registers_mixed(fake_server):
    """Live and dead servers in one round: live replies arrive, dead are None."""
    (dead,) = _dead_ports(1)
    values = read_registers([
        (fake_server.base_port, CONFIGURED_REG),
        (dead, CONFIGURED_REG),
        (fake_server.base_port, CONFIGURING_REG),
        (fake_server.base_port, 'AMCc.Broken'),
    ], timeout=0.5)
    assert values == [True, None, False, None]


@pytest.fixture
def agent():
    mock_agent = mock.MagicMock()
    return SmurfHammerAgent(mock_agent)


def test_monitor_one_pass(agent):
    """One monitor pass over configured, configuring and unreachable slots."""
    reads = {
        (server_port(2), CONFIGURED_REG): True,
        (server_port(2), CONFIGURING_REG): False,
        (server_port(3), CONFIGURED_REG): False,
        (server_port(3), CONFIGURING_REG): True,
        # slot 5 never answers
    }
    rounds = []

    def fake_read_registers(requests, timeout=2.0, context=None):
        rounds.append(list(requests))
        return [reads.get(r) for r in requests]

    def stop_after_first_pass(_):
        agent._monitor_running = False

    session = mock.MagicMock()
    with mock.patch('socs.agents.smurf_hammer.agent.read_registers',
                    fake_read_registers), \
            mock.patch('time.sleep', stop_after_first_pass):
        ok, msg = agent.monitor(session, {})

    assert ok is True
    assert session.data['slots'] == {
        2: {'configured': True, 'configuring': False},
        3: {'configured': False, 'configuring': True},
        5: {'configured': None, 'configuring': None},
    }
    # every register of every slot goes out in a single round
    assert len(rounds) == 1
    assert sorted(rounds[0]) == sorted(
        (server_port(s), reg) for s in (2, 3, 5)
        for reg in (CONFIGURED_REG, CONFIGURING_REG))

    feed = agent.agent.publish_to_feed.call_args.args[1]
    assert feed['block_name'] == 'system_configured'
    assert feed['data'] == {
        'configured_s2': 1, 'configuring_s2': 0,
        'configured_s3': 0, 'configuring_s3': 1,
        'configured_s5': -1, 'configuring_s5': -1,
    }
