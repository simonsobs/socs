import sys
sys.path.insert(0, './agents/lakeshore372/')
from LS372_agent import LS372_Agent

from ocs.ocs_agent import OpSession

import pytest
from unittest import mock

import txaio
txaio.use_twisted()


# Mocks and fixtures
def mock_connection():
    """Mock a standard connection."""
    return mock.MagicMock()


def mock_failed_connection():
    """Mock an unhandled error during connection.

    Typically a failed connection will raise a ConnectionError, but we want to
    check unhandled exceptions in the tests too.

    """
    failed_con = mock.Mock(side_effect=RuntimeError('Unhandled error'))
    return failed_con


@pytest.fixture
def mock_agent():
    """Test fixture to setup a mocked OCSAgent."""
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')

    return mock_agent


# Mock responses from the 372
def mock_372_msg():
    mock_msg = mock.Mock()

    values = {'*IDN?': 'LSCI,MODEL372,LSA23JD,1.3',
              'SCAN?': '01,1',
              'INSET? A': '0,010,003,00,1',
              'INNAME? A': 'Input A',
              'INTYPE? A': '1,04,0,15,0,2',
              'TLIMIT? A': '+0000',
              'OUTMODE? 0': '2,6,1,0,0,001',
              'HTRSET? 0': '+120.000,8,+0000.00,1',
              'OUTMODE? 2': '4,16,1,0,0,001',
              'HTRSET? 2': '+120.000,8,+0000.00,1'}

    for i in range(1, 17):
        values[f'INSET? {i}'] = '1,007,003,21,1'
        values[f'INNAME? {i}'] = f'Channel {i:02}'
        values[f'INTYPE? {i}'] = '0,07,1,10,0,1'
        values[f'TLIMIT? {i}'] = '+0000'

    def side_effect(arg):
        return values[arg]

    mock_msg.side_effect = side_effect

    return mock_msg


# Tests
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_task(mock_agent):
    """Run init_lakeshore_task, mocking a connection and the 372 messaging.
    This should be as if the initialization worked without issue.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    res = agent.init_lakeshore_task(session, None)

    print(res)
    print(agent.initialized)
    print(session.encoded())
    assert agent.initialized is True
    assert res[0] is True


@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_task_already_initialized(mock_agent):
    """Initializing an already initialized LS372_Agent should just return True.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    agent.init_lakeshore_task(session, None)
    res = agent.init_lakeshore_task(session, None)
    assert agent.initialized is True
    assert res[0] is True


# If we don't patch the reactor out, it'll mess up pytest when stop is called
@mock.patch('LS372_agent.reactor', mock.MagicMock())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_task_failed_connection(mock_agent):
    """Leaving off the connection Mock, if the connection fails the init task
    should fail and return False.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    res = agent.init_lakeshore_task(session, None)
    assert res[0] is False


# If we don't patch the reactor out, it'll mess up pytest when stop is called
@mock.patch('LS372_agent.reactor', mock.MagicMock())
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_failed_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_task_unhandled_error(mock_agent):
    """If we cause an unhandled exception during connection init task should
    also fail and return False.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    res = agent.init_lakeshore_task(session, None)
    assert res[0] is False


@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_task_auto_acquire(mock_agent):
    """If we initalize and pass the auto_acquire param, we should expect the
    Agent to make a start call for the acq process, given the params in acq_params.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    res = agent.init_lakeshore_task(session, {'auto_acquire': True, 'acq_params': {'test': 1}})
    assert res[0] is True
    agent.agent.start.assert_called_once_with('acq', {'test': 1})
