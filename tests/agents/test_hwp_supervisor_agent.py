import os
import time
import sys
sys.path.insert(0, '../agents/hwp_supervisor/')
from hwp_supervisor import HwpSupervisorAgent

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from ocs.ocs_agent import OpSession
from ocs.ocs_client import OCSReply

import pytest
from unittest import mock

import txaio
txaio.use_twisted()

# Set the OCS_CONFIG_DIR so we read the local default.yaml file always
os.environ['OCS_CONFIG_DIR'] = os.getcwd()

# Mocks and fixtures


def mock_connection():
    """Mock a standard connection."""
    return mock.MagicMock()


def create_session(op_name):
    """Create an OpSession with a mocked app for testing."""
    mock_app = mock.MagicMock()
    session = OpSession(1, op_name, app=mock_app)

    return session


@pytest.fixture
def agent():
    """Test fixture to setup a mocked OCSAgent."""
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')
    agent = HwpSupervisorAgent(mock_agent, 'hwp_supervisor.yaml')

    return agent


# Tests
def test_hwp_supervisor_load_config(agent):
    session = create_session('load_config')
    res = agent.load_config(session, None)

    print(res)
    print(agent._config)
    print(session.encoded())
    assert 'lakeshore-device' in agent._config
    assert res[0] is True


@patch('ocs.client_http.ControlClient', MagicMock())
def test_hwp_supervisor_init_clients(agent):
    # load config first so we know what clients to init
    session = create_session('load_config')
    res = agent.load_config(session, None)

    session = create_session('init_clients')
    res = agent.init_clients(session, None)

    print(res)
    print('CLIENTS:', agent.clients)
    print(session.encoded())
    assert agent.clients is not None
    assert res[0] is True


def test_hwp_supervisor_override(agent):
    session = create_session('override')
    status = {'status': 'warn',
              'expiration': (datetime.now() + timedelta(seconds=10)).strftime("%Y-%m-%d %H:%M:%S"),
              'worry': 1}
    res = agent.override_status(session, params=status)

    print(res)
    print(session.encoded())
    assert res[0] is True


monitor_testcases = [
    ({'timestamp': time.time(),
      'fields': {"Channel_1": {"T": 30}}},
     0),
    ({'timestamp': time.time(),
      'fields': {"Channel_1": {"T": 60}}},
     1),
    ({'timestamp': time.time() - 70,
      'fields': {"Channel_1": {"T": 30}}},
     1)]


@patch('ocs.client_http.ControlClient', MagicMock())
@patch('hwp_supervisor.time.sleep', return_value=None)
@pytest.mark.parametrize("status,worry", monitor_testcases)
def test_hwp_supervisor_monitor(_sleep_patch, status, worry, agent):
    # load config first so we know what clients to init
    session = create_session('load_config')
    res = agent.load_config(session, None)

    # mock clients
    agent.clients = {'rotation-agent1': MagicMock(),
                     'gripper-agent1': MagicMock(),
                     'encoder-agent1': MagicMock(),
                     'lakeshore-240-1': MagicMock(),
                     'ups-1': MagicMock()}

    # set override
    agent.override = True
    agent.status = {'status': 'ok',
                    'expires': (datetime.now() + timedelta(seconds=0.5)).strftime("%Y-%m-%d %H:%M:%S"),
                    'worry': 0}

    # Setup responses from lakeshore agent
    def return_status():
        session = create_session('acq')
        nonlocal status
        session.data = status
        reply = OCSReply(3, 'test', session.encoded())
        return reply
    agent.clients['lakeshore-240-1'].acq.status = MagicMock(side_effect=return_status)

    # monitor
    session = create_session('monitor')
    res = agent.monitor(session, params={"test_mode": True})

    print(res)
    print(session.encoded())
    assert session.data['worry'] == worry
    assert res[0] is True


shutdown_testcases = [
    # successful stop
    ({'approx_hwp_freq': 0.0,
      'encoder_last_updated': time.time() - 2,
      'irig_time': 1659486983,
      'irig_last_updated': 1659486983.8985631},
     True),
    # no hwp freq
    ({'approx_hwp_freq': -1,
      'encoder_last_updated': time.time() - 2,
      'irig_time': 1659486983,
      'irig_last_updated': 1659486983.8985631},
     False),
    # stale data
    ({'approx_hwp_freq': 0,
      'encoder_last_updated': time.time() - 70,
      'irig_time': 1659486983,
      'irig_last_updated': 1659486983.8985631},
     False),
    # still spinning
    ({'approx_hwp_freq': 2,
      'encoder_last_updated': time.time() - 2,
      'irig_time': 1659486983,
      'irig_last_updated': 1659486983.8985631},
     False)]


@patch('ocs.client_http.ControlClient', MagicMock())
@patch('hwp_supervisor.time.sleep', return_value=None)
@pytest.mark.parametrize("status,result", shutdown_testcases)
def test_hwp_supervisor_shutdown(_sleep_patch, status, result, agent):
    # load config first so we know what clients to init
    session = create_session('load_config')
    res = agent.load_config(session, None)

    # mock clients
    agent.clients = {'rotation-agent1': MagicMock(),
                     'gripper-agent1': MagicMock(),
                     'encoder-agent1': MagicMock()}

    # Setup responses from encoder agent
    def return_status():
        session = create_session('acq')
        nonlocal status
        session.data = status
        reply = OCSReply(3, 'test', session.encoded())
        return reply
    agent.clients['encoder-agent1'].acq.status = MagicMock(side_effect=return_status)

    session = create_session('shutdown')
    # print(dir(session))
    res = agent.shutdown(session, None)

    # print('RES', res)
    # print('CLIENTS:', agent.clients)
    # print(session.encoded())
    assert agent.clients is not None
    assert res[0] is result
