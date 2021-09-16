import sys
sys.path.insert(0, './agents/lakeshore372/')
from LS372_agent import LS372_Agent

from unittest import mock

def test_bluefors():
    mock_agent = mock.MagicMock()
    agent = LS372_Agent(mock_agent, 'mock372', '127.0.0.1' )
    return agent
