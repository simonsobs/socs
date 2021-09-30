import sys
sys.path.insert(0, '../agents/bluefors/')
from bluefors_log_tracker import BlueforsAgent

from unittest import mock

def test_bluefors():
    mock_agent = mock.MagicMock()
    agent = BlueforsAgent(mock_agent, './')
    return agent
