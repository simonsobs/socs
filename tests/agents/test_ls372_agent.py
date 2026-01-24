from unittest import mock

import pytest
import txaio
from ocs.ocs_agent import OpSession

from socs.agents.lakeshore372.agent import LS372_Agent

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
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1')

    return agent


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

    # Heaters
    values.update({'RANGE? 0': '0',
                   'RANGE? 2': '1',
                   'STILL?': '+10.60',
                   'HTR?': '+00.0005E+00'})

    # Senor readings
    values.update({'KRDG? 1': '+293.873E+00',
                   'SRDG? 1': '+108.278E+00',
                   'KRDG? A': '+00.0000E-03',
                   'SRDG? A': '+000.000E+09'})

    def side_effect(arg):
        # All commands just return ''
        if '?' not in arg:
            return ''

        # Mocked example query responses
        return values[arg]

    mock_msg.side_effect = side_effect

    return mock_msg


# Tests
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore(agent):
    """Run init_lakeshore, mocking a connection and the 372 messaging.
    This should be as if the initialization worked without issue.

    """
    session = create_session('init_lakeshore')
    res = agent.init_lakeshore(session, None)

    print(res)
    print(agent.initialized)
    print(session.encoded())
    assert agent.initialized is True
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_already_initialized(agent):
    """Initializing an already initialized LS372_Agent should just return True.

    """
    session = create_session('init_lakeshore')
    agent.init_lakeshore(session, None)
    res = agent.init_lakeshore(session, None)
    assert agent.initialized is True
    assert res[0] is True


# If we don't patch the reactor out, it'll mess up pytest when stop is called
@mock.patch('socs.agents.lakeshore372.agent.reactor', mock.MagicMock())
@mock.patch('socs.tcp.TCPInterface._connect', mock_failed_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_failed_connection(agent):
    """If the connection fails the init task should fail and return False."""
    session = create_session('init_lakeshore')
    res = agent.init_lakeshore(session, None)
    assert res[0] is False


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_init_lakeshore_auto_acquire(agent):
    """If we initalize and pass the auto_acquire param, we should expect the
    Agent to make a start call for the acq process, given the params in acq_params.

    """
    session = create_session('init_lakeshore')
    res = agent.init_lakeshore(session, {'auto_acquire': True, 'acq_params': {'test': 1}})
    assert res[0] is True
    agent.agent.start.assert_called_once_with('acq', {'test': 1})


# enable_control_chan
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_enable_control_chan(agent):
    """Normal operation of 'enable_control_chan' task."""
    session = create_session('enable_control_chan')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    res = agent.enable_control_chan(session, params=None)
    assert res[0] is True


# disable_control_chan
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_disable_control_chan(agent):
    """Normal operation of 'disable_control_chan' task."""
    session = create_session('disable_control_chan')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    res = agent.disable_control_chan(session, params=None)
    assert res[0] is True


# acq
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_acq(agent):
    """Test running the 'acq' Process once."""
    session = create_session('acq')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'run_once': True}
    res = agent.acq(session, params=params)
    assert res[0] is True

    assert session.data['fields']['Channel_01']['T'] == 293.873
    assert session.data['fields']['Channel_01']['R'] == 108.278


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_acq_w_control_chan(agent):
    """Test running the 'acq' Process once with control channel active."""
    session = create_session('acq')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # Turn on control channel
    agent.enable_control_chan(session, None)

    params = {'run_once': True}
    res = agent.acq(session, params=params)
    assert res[0] is True

    assert session.data['fields']['control']['T'] == 0.0
    assert session.data['fields']['control']['R'] == 0.0


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_acq_w_sample_heater(agent):
    """Test running the 'acq' Process once with sample heater active."""
    session = create_session('acq')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'run_once': True, 'sample_heater': True}
    res = agent.acq(session, params=params)
    assert res[0] is True


# stop_acq
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_stop_acq_not_running(agent):
    """'stop_acq' should return False if acq Process isn't running."""
    session = create_session('stop_acq')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    res = agent._stop_acq(session, params=None)
    assert res[0] is False


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_stop_acq_while_running(agent):
    """'stop_acq' should return True if acq Process is running."""
    session = create_session('stop_acq')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # Mock running the acq Process
    agent.take_data = True

    res = agent._stop_acq(session, params=None)
    assert res[0] is True
    assert agent.take_data is False


# set_heater_range
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_sample_heater(agent):
    """Set sample heater to different range than currently set. Normal
    operation.

    """
    session = create_session('set_heater_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'range': 1e-3, 'heater': 'sample', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_still_heater(agent):
    """Set still heater to different range than currently set. Normal
    operation.

    """
    session = create_session('set_heater_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'range': 'On', 'heater': 'still', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_range_identical_range(agent):
    """Set heater to same range as currently set. Should not change range, just
    return True.

    """
    session = create_session('set_heater_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # Mock the heater interface
    # agent.module.sample_heater.get_heater_range = mock.Mock(return_value="Off")
    agent.module.sample_heater.set_heater_range = mock.Mock()

    params = {'range': 'Off', 'heater': 'sample', 'wait': 0}
    res = agent.set_heater_range(session, params)
    assert res[0] is True
    agent.module.sample_heater.set_heater_range.assert_not_called()


# set_excitation_mode
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_excitation_mode(agent):
    """Normal operation of 'set_excitation_mode' task."""
    session = create_session('set_excitation_mode')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1, 'mode': 'current'}
    res = agent.set_excitation_mode(session, params)
    assert res[0] is True


# set_excitation
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_excitation(agent):
    """Normal operation of 'set_excitation' task."""
    session = create_session('set_excitation')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1, 'value': 1e-9}
    res = agent.set_excitation(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_excitation_already_set(agent):
    """Setting to already set excitation value."""
    session = create_session('set_excitation')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1, 'value': 2e-3}
    res = agent.set_excitation(session, params)
    assert res[0] is True


# get_excitation
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_get_excitation(agent):
    session = create_session('get_excitation')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1}
    res = agent.get_excitation(session, params)
    assert res[0] is True


# set_resistance_range
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_resistance_range(agent):
    session = create_session('get_resistance_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1, 'resistance_range': 2}
    res = agent.set_resistance_range(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_resistance_range_current_range(agent):
    session = create_session('get_resistance_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # 372 mock defaults to 63.2
    params = {'channel': 1, 'resistance_range': 63.2}
    res = agent.set_resistance_range(session, params)
    assert res[0] is True


# get_resistance_range
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_get_resistance_range_current_range(agent):
    session = create_session('get_resistance_range')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # 372 mock defaults to 63.2
    params = {'channel': 1}
    res = agent.get_resistance_range(session, params)
    assert res[0] is True


# set_dwell
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_dwell(agent):
    session = create_session('set_dwell')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # 372 mock defaults to 63.2
    params = {'channel': 1, 'dwell': 3}
    res = agent.set_dwell(session, params)
    assert res[0] is True


# get_dwell
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_get_dwell(agent):
    session = create_session('get_dwell')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    # 372 mock defaults to 63.2
    params = {'channel': 1}
    res = agent.get_dwell(session, params)
    assert res[0] is True


# set_pid
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_pid(agent):
    """Normal operation of 'set_pid' task."""
    session = create_session('set_pid')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'P': 40, 'I': 2, 'D': 0}
    res = agent.set_pid(session, params)
    assert res[0] is True


# set_active_channel
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_active_channel(agent):
    """Normal operation of 'set_active_channel' task."""
    session = create_session('set_active_channel')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'channel': 1}
    res = agent.set_active_channel(session, params)
    assert res[0] is True


# set_autoscan
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_autoscan_on(agent):
    """Normal operation of 'set_autoscan' task."""
    session = create_session('set_autoscan')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'autoscan': True}
    res = agent.set_autoscan(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_autoscan_off(agent):
    """Normal operation of 'set_autoscan' task."""
    session = create_session('set_autoscan')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'autoscan': False}
    res = agent.set_autoscan(session, params)
    assert res[0] is True


# servo_to_temperature
# this task should really get reworked, mostly into a client
# check_temperature_stability
# this task should become a client function really


# set_output_mode
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_output_mode_still(agent):
    """Normal operation of 'set_output_mode' task for the still heater."""
    session = create_session('set_output_mode')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'heater': 'still', 'mode': 'Off'}
    res = agent.set_output_mode(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_output_mode_sample(agent):
    """Normal operation of 'set_output_mode' task for the sample heater."""
    session = create_session('set_output_mode')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'heater': 'sample', 'mode': 'Off'}
    res = agent.set_output_mode(session, params)
    assert res[0] is True


# set_heater_output
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_output_still(agent):
    """Normal operation of 'set_heater_output' task for the still heater."""
    session = create_session('set_heater_output')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'heater': 'still', 'output': 50}
    res = agent.set_heater_output(session, params)
    assert res[0] is True


@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_heater_output_sample(agent):
    """Normal operation of 'set_heater_output' task for the sample heater."""
    session = create_session('set_heater_output')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'heater': 'sample', 'output': 50}
    res = agent.set_heater_output(session, params)
    assert res[0] is True


# set_still_output
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_set_still_output(agent):
    """Normal operation of 'set_still_output' task."""
    session = create_session('set_still_output')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    params = {'output': 50}
    res = agent.set_still_output(session, params)
    assert res[0] is True


# get_still_output
@mock.patch('socs.tcp.TCPInterface._connect', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_372_msg())
def test_ls372_get_still_output(agent):
    """Normal operation of 'get_still_output' task."""
    session = create_session('get_still_output')

    # Have to init before running anything else
    agent.init_lakeshore(session, None)

    res = agent.get_still_output(session, params=None)
    assert res[0] is True
    assert session.data['still_heater_still_out'] == '+10.60'
