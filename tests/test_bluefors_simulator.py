import pytest

from socs.testing.bluefors_simulator import LogSimulator


@pytest.fixture
def logsim(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    sim = LogSimulator(d)
    yield sim


def test_log_simulator(logsim):
    print(logsim.log_dir)


def test_write_thermometer_files(logsim):
    logsim.write_thermometer_files()


def test_write_flowmeter_file(logsim):
    logsim.write_flowmeter_file()


def test_write_maxigauge_file(logsim):
    logsim.write_maxigauge_file()


def test_write_channel_file(logsim):
    logsim.write_channel_file()


def test_write_status_file(logsim):
    logsim.write_status_file()


def test_write_heater_file(logsim):
    logsim.write_heater_file()
