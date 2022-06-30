import sys
sys.path.insert(0, '../agents/smurf_file_emulator/')
from smurf_file_emulator import SmurfFileEmulator, make_parser

from unittest import mock

import txaio
txaio.use_twisted()


def create_agent(base_dir, file_duration=10, frame_len=2,
                 nchans=1024):
    """Test fixture to setup a mocked OCSAgent."""
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')
    parser = make_parser()
    args = parser.parse_args(args=[
        '--stream-id', 'test_em', '--base-dir', base_dir,
        '--file-duration', str(file_duration), '--frame-len', str(frame_len),
        '--sample-rate', str(10),
    ])
    agent = SmurfFileEmulator(mock_agent, args)
    return agent


def test_uxm_setup(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    session.data = {}
    emulator.uxm_setup(session, {'test_mode': True})


def test_uxm_relock(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    session.data = {}
    emulator.uxm_relock(session, {'test_mode': True})


def test_take_noise(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    session.data = {}
    emulator.uxm_relock(session, {'test_mode': True})
    emulator.take_noise(session)


def test_take_bgmap(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    session.data = {}
    emulator.take_bgmap(session)


def test_take_iv(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    emulator.take_iv(session)


def test_take_bias_steps(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    emulator.take_bias_steps(session)


def test_bias_dets(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    emulator.bias_dets(session)


def test_stream(tmp_path):
    emulator = create_agent(str(tmp_path), file_duration=1, frame_len=.5)
    session = mock.MagicMock()
    session.data = {}
    emulator.uxm_relock(session, {'test_mode': True})
    emulator.stream(session, params={'duration': 2})
