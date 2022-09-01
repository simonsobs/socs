from socs.agents.bluefors.agent import BlueforsAgent

from unittest import mock


def test_bluefors():
    mock_agent = mock.MagicMock()
    agent = BlueforsAgent(mock_agent, './')
    return agent
