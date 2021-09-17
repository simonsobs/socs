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
              'SCAN 1,1': '',
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

    # Channel settings
    values.update({'INTYPE 1,1,07,1,10,0,1': '',
                   'INTYPE 1,0,1,1,10,0,1': ''})

    # Heaters
    values.update({'RANGE? 0': '0',
                   'RANGE 0 4': '',
                   'RANGE? 2': '1',
                   'PID 0,40,2,0': '',
                   'OUTMODE 2,0,16,1,0,0,001': '',
                   'MOUT 2 50': ''})

    # TODO: get any non ? command to return ''
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


# set_heater_range
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_sample_heater(mock_agent):
    """Set sample heater to different range than currently set. Normal
    operation.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_heater_range', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'range': 1e-3, 'heater': 'sample', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True


@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_still_heater(mock_agent):
    """Set still heater to different range than currently set. Normal
    operation.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_heater_range', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'range': 'On', 'heater': 'still', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True


@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_identical_range(mock_agent):
    """Set heater to same range as currently set. Should not change range, just
    return True.

    """
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_heater_range', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    # Mock the heater interface
    #agent.module.sample_heater.get_heater_range = mock.Mock(return_value="Off")
    agent.module.sample_heater.set_heater_range = mock.Mock()

    params = {'range': 'Off', 'heater': 'sample', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True
    agent.module.sample_heater.set_heater_range.assert_not_called()


# set_excitation_mode
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_excitation_mode(mock_agent):
    """Normal operation of 'set_excitation_mode' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_excitation_mode', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'channel': 1, 'mode': 'current'}
    res = agent.set_excitation_mode(session, params)
    assert res[0] is True


# set_excitation
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_excitation(mock_agent):
    """Normal operation of 'set_excitation' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_excitation', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'channel': 1, 'value': 1e-9}
    res = agent.set_excitation(session, params)
    assert res[0] is True


# set_pid
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_pid(mock_agent):
    """Normal operation of 'set_pid' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_pid', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'P': 40, 'I': 2, 'D': 0}
    res = agent.set_pid(session, params)
    assert res[0] is True


# set_active_channel
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_active_channel(mock_agent):
    """Normal operation of 'set_active_channel' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_active_channel', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'channel': 1}
    res = agent.set_active_channel(session, params)
    assert res[0] is True


# set_autoscan
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_autoscan(mock_agent):
    """Normal operation of 'set_autoscan' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_autoscan', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'autoscan': True}
    res = agent.set_autoscan(session, params)
    assert res[0] is True


# servo_to_temperature
## this task should really get reworked, mostly into a client
# check_temperature_stability
## this task should become a client function really


# set_output_mode
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_output_mode(mock_agent):
    """Normal operation of 'set_output_mode' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_output_mode', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'heater': 'still', 'mode': 'Off'}
    res = agent.set_output_mode(session, params)
    assert res[0] is True


# set_heater_output
@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_output(mock_agent):
    """Normal operation of 'set_heater_output' task."""
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    mock_app = mock.MagicMock()
    session = OpSession(1, 'set_heater_output', app=mock_app)

    # Have to init before running anything else
    agent.init_lakeshore_task(session, None)

    params = {'heater': 'still', 'output': 50}
    res = agent.set_heater_output(session, params)
    assert res[0] is True


# set_still_output
# get_still_output
