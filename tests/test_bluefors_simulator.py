import pytest

from socs.testing.bluefors_simulator import LogSimulator


@pytest.fixture
def logsim(tmp_path):
    d = tmp_path / "logs"
    d.mkdir()
    sim = LogSimulator(d)
    yield sim


def check_written_logs(filename, line):
    with open(filename, 'r') as f:
        logline = f.readline()

    assert logline == line


def test_write_thermometer_files(logsim):
    resp = logsim.write_thermometer_files()
    for file in resp:
        check_written_logs(*file)


def test_write_flowmeter_file(logsim):
    resp = logsim.write_flowmeter_file()
    check_written_logs(*resp[0])


def test_write_maxigauge_file(logsim):
    resp = logsim.write_maxigauge_file()
    check_written_logs(*resp[0])


def test_write_channel_file(logsim):
    resp = logsim.write_channel_file()
    check_written_logs(*resp[0])


def test_write_status_file(logsim):
    resp = logsim.write_status_file()
    check_written_logs(*resp[0])


def test_write_heater_file(logsim):
    resp = logsim.write_heater_file()
    check_written_logs(*resp[0])
