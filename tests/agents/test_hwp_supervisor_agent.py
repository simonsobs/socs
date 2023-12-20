from unittest import mock

import txaio
from ocs.ocs_agent import OpSession

from socs.agents.hwp_supervisor.agent import HWPSupervisor, make_parser


def create_session(op_name):
    """Create an OpSession with a mocked app for testing."""
    mock_app = mock.MagicMock()
    session = OpSession(1, op_name, app=mock_app)

    return session


def test_hwp_supervisor_agent():
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')
    parser = make_parser()
    args = parser.parse_args(args=['--hwp-encoder-id', 'test'])
    agent = HWPSupervisor(mock_agent, args)
    session = create_session('monitor')
    params = {'test_mode': True}
    agent.monitor(session, params)
    monitored_sessions = session.data['monitored_sessions']
    assert monitored_sessions['temperature']['status'] == 'no_agent_provided'
    assert monitored_sessions['encoder']['status'] == 'test_mode'
