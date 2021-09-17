import sys
sys.path.insert(0, './agents/lakeshore372/')
from LS372_agent import LS372_Agent

from ocs.ocs_agent import OpSession

import pytest
from unittest import mock

import txaio
txaio.use_twisted()

# Mocks and fixtures
#def mock_connection_send_recv():
#    mock_con = mock.Mock()
#    mock_con.send = lambda s: len(s.encode('utf-8'))
#    mock_con.recv = mock.Mock()
#
#    values = {'*IDN?': 'LSCI,MODEL372,LSA23JD,1.3'}
#    def side_effect(arg):
#        return values[arg]
#    mock_con.recv.side_effect = side_effect
#
#    return mock_con

def mock_connection():
    return mock.MagicMock()

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
          'HTRSET? 2': '+120.000,8,+0000.00,1',
}

for i in range(1, 17):
    values[f'INSET? {i}'] = '1,007,003,21,1'
    values[f'INNAME? {i}'] = f'Channel {i:02}'
    values[f'INTYPE? {i}'] = '0,07,1,10,0,1'
    values[f'TLIMIT? {i}'] = '+0000'

def side_effect(arg):
    return values[arg]

mock_msg.side_effect = side_effect


# Tests
def test_ls372(mock_agent):
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1' )
    return agent

@mock.patch('socs.Lakeshore.Lakeshore372._establish_socket_connection', mock_connection())
@mock.patch('socs.Lakeshore.Lakeshore372.LS372.msg', mock_msg)
def test_ls372_init_lakeshore_task(mock_agent):
    #mock_agent = mock.MagicMock()
    #log = txaio.make_logger()
    #txaio.start_logging(level='debug')
    #mock_agent.log = log

    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1' )

    mock_app = mock.MagicMock()
    session = OpSession(1, 'init_lakeshore', app=mock_app)
    response = agent.init_lakeshore_task(session, None)
    print(response)
    return response
