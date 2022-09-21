from unittest import mock

from socs.agents.bluefors.agent import BlueforsAgent


def test_bluefors():
    mock_agent = mock.MagicMock()
    agent = BlueforsAgent(mock_agent, './')
    return agent
