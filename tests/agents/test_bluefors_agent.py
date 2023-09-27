import time
from datetime import date, timedelta
from unittest import mock

from socs.agents.bluefors.agent import BlueforsAgent, LogTracker
from socs.testing.bluefors_simulator import create_bluefors_simulator

simulator = create_bluefors_simulator()


def test_bluefors():
    mock_agent = mock.MagicMock()
    agent = BlueforsAgent(mock_agent, './')
    return agent


class TestLogTracker:
    def test_open_all_logs(self, simulator):
        track = LogTracker(simulator.log_dir)
        track.open_all_logs()
        assert track.file_objects != {}

    def test_set_active_date(self, simulator):
        track = LogTracker(simulator.log_dir)
        current_date = track.date

        # emulate a date rotation
        yesterday = date.fromtimestamp(time.time()) - timedelta(days=1)
        track.date = yesterday
        track.set_active_date()
        assert track.date == current_date

    def test_check_open_files(self, simulator):
        track = LogTracker(simulator.log_dir)
        track.check_open_files()
        assert track.file_objects != {}

    def test_reopen_file(self, simulator):
        track = LogTracker(simulator.log_dir)
        track.open_all_logs()
        file_ = next(iter(track.file_objects))
        track.reopen_file(file_)
        assert track.file_objects[file_]['file_object'].name == file_
