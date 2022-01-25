import sys
sys.path.insert(0, '../agents/smurf_file_emulator/')
import os
from argparse import Namespace
from smurf_file_emulator import SmurfFileEmulator

from ocs.ocs_agent import OpSession

import pytest
from unittest import mock

import txaio
txaio.use_twisted()

def create_agent(base_dir, file_duration=10):
    """Test fixture to setup a mocked OCSAgent."""
    mock_agent = mock.MagicMock()
    log = txaio.make_logger()
    txaio.start_logging(level='debug')
    mock_agent.log = log
    log.info('Initialized mock OCSAgent')
    args = Namespace(
        stream_id='test_em', base_dir=base_dir,
        stream_on_start=False, file_duration=file_duration
    )

    agent = SmurfFileEmulator(mock_agent, args)
    return agent

def test_tune_up(tmp_path):
    emulator = create_agent(str(tmp_path))
    session = mock.MagicMock()
    emulator.tune_dets(session)

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
    emulator = create_agent(str(tmp_path), file_duration=0.2)
    session = mock.MagicMock()
    emulator.stream(session, params={'duration': 1})
