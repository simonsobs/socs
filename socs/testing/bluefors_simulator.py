import os
import random
import time
from datetime import datetime, timezone

# Rules
# Observations about the behavior of the log files. This is all reverse
# engineered from the bluefors log output.
#
# * All Lakeshore measurements share timestamps.
# * Channels can appear at any time, or not exist at all.
# * Other logs do not share timestamps, this includes:
#   * Channels
#   * Flowmeter
#   * Maxigauge


def mkdir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


def make_therm_file_list(channels, date, directory=None):
    """Make list of files to create/open.

    Parameters
    ----------
    channels : list
        List of channel numbers (ints)
    date : str
        Date in format YY-MM-DD

    Returns
    --------

    """
    files = []
    types = ['P', 'R', 'T']
    for channel in channels:
        for t in types:
            if directory:
                _file = f'CH{channel} {t} {date}.log'
                _full_path = os.path.join(directory, _file)
                files.append(_full_path)
            else:
                files.append(f'CH{channel} {t} {date}.log')

    return files


def make_utc_time_string(format_):
    """Make a UTC time string in given format.

    Parameters
    ----------
    format_ : str
        datetime.strftime style formatting

    Returns
    -------
    str
        Formatted string with current time in UTC.

    """
    t_dt = datetime.fromtimestamp(time.time())
    t_dt = t_dt.astimezone(tz=timezone.utc)

    return t_dt.strftime(format_)


class LogSimulator:
    """Bluefors log simulator.

    This object knows how to create a directory and files for "today" and write
    random data to them in the Bluefors log format. This can be used to test
    the Bluefors Agent.

    Parameters
    ----------
    log_dir : str
        Path for the directory to write log files to. Defaults to "./sim/".

    """

    def __init__(self, log_dir="./sim/"):
        self.file_objects = {}
        self.create_file_objects(log_dir=log_dir)

    def create_file_objects(self, log_dir):
        # let's forego log rotation, so just make logs for today and only today
        file_date_str = make_utc_time_string("%y-%m-%d")

        filepath = os.path.join(log_dir, file_date_str,)
        mkdir(filepath)

        self.file_objects['thermometers'] = {}
        thermometer_files = make_therm_file_list([1, 2, 5, 6, 8], file_date_str, filepath)
        for _file in thermometer_files:
            self.file_objects['thermometers'][_file] = open(_file, 'a')

        flowmeter_file = os.path.join(filepath, f'Flowmeter {file_date_str}.log')
        self.file_objects['flowmeter'] = open(flowmeter_file, 'a')

        maxigauge_file = os.path.join(filepath, f'maxigauge {file_date_str}.log')
        self.file_objects['maxigauge'] = open(maxigauge_file, 'a')

        channel_state_file = os.path.join(filepath, f'Channels {file_date_str}.log')
        self.file_objects['channels'] = open(channel_state_file, 'a')

        status_state_file = os.path.join(filepath, f'Status_{file_date_str}.log')
        self.file_objects['status'] = open(status_state_file, 'a')

        heater_file = os.path.join(filepath, f'heaters_{file_date_str}.log')
        self.file_objects['heaters'] = open(heater_file, 'a')

    def write_thermometer_files(self):
        # all thermometers share a timestamp, so use a single time_str
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        for k, f in self.file_objects['thermometers'].items():
            print('writing to', k)
            data_str = random.randint(0, 100) / 100
            full_str = " {time},{data}".format(time=time_str, data=data_str)
            print(full_str)
            f.write(full_str + '\n')
            f.flush()

    def write_flowmeter_file(self):
        # Flow isn't necessarily sync'd to temps so lets not do that
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        # print('writing to', k)
        data_str = random.randint(0, 100) / 100
        full_str = " {time},{data}".format(time=time_str, data=data_str)
        print(full_str)
        self.file_objects['flowmeter'].write(full_str + '\n')
        self.file_objects['flowmeter'].flush()

    def write_maxigauge_file(self):
        # maxigauge readings
        pressure_channels = ['CH1', 'CH2', 'CH3', 'CH4', 'CH5', 'CH6']

        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        ch1_state = random.randint(0, 1)
        data = {}
        for p_ch in pressure_channels:
            data[p_ch] = '%.2E' % float(random.randint(0, 100) / 100)

        if ch1_state == 0:
            data['CH1'] = '2.00E-02'
        full_str = f"{time_str},CH1,        ,{ch1_state}, {data['CH1']},0,1,"\
                   f"CH2,       ,1, {data['CH2']},1,1,"\
                   f"CH3,       ,1, {data['CH3']},0,1,"\
                   f"CH4,       ,1, {data['CH4']},0,1,"\
                   f"CH5,       ,1, {data['CH5']},0,1,"\
                   f"CH6,       ,1, {data['CH6']},0,1,"
        print(full_str)
        self.file_objects['maxigauge'].write(full_str + '\n')
        self.file_objects['maxigauge'].flush()

    def write_channel_file(self):
        # channels
        state_channels = ['v11', 'v2', 'v1', 'turbo1', 'v12', 'v3', 'v10',
                          'v14', 'v4', 'v13', 'compressor', 'v15', 'v5', 'hs-still', 'v21', 'v16', 'v6',
                          'scroll1', 'v17', 'v7', 'scroll2', 'v18', 'v8', 'pulsetube', 'v19', 'v20',
                          'v9', 'hs-mc', 'ext']

        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        full_str = f"{time_str},1"
        for ch in state_channels:
            random_state = random.randint(0, 1)
            full_str += f",{ch},{random_state}"
        print(full_str)
        self.file_objects['channels'].write(full_str + '\n')
        self.file_objects['channels'].flush()

    def write_status_file(self):
        # status readings
        status_channels = ['tc400errorcode', 'tc400ovtempelec', 'tc400ovtemppump',
                           'tc400setspdatt', 'tc400pumpaccel', 'tc400commerr', 'tc400errorcode_2',
                           'tc400ovtempelec_2', 'tc400ovtemppump_2', 'tc400setspdatt_2',
                           'tc400pumpaccel_2', 'tc400commerr_2', 'ctrl_pres', 'cpastate', 'cparun',
                           'cpawarn', 'cpaerr', 'cpatempwi', 'cpatempwo', 'cpatempo', 'cpatemph', 'cpalp',
                           'cpalpa', 'cpahp', 'cpahpa', 'cpadp', 'cpacurrent', 'cpahours', 'cpapscale',
                           'cpatscale', 'cpasn', 'cpamodel']

        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")

        data = {}
        for s_ch in status_channels:
            if 'tc400' in s_ch:
                if 'tc400setspdatt' in s_ch:
                    data[s_ch] = '%.5E' % 1
                else:
                    data[s_ch] = '%.5E' % 0
            else:
                data[s_ch] = '%.5E' % float(random.randint(0, 1000000) / 100000)
        data_str = ''
        for ch in status_channels:
            data_str += f",{ch},{data[ch]}"
        full_str = f"{time_str}{data_str}"

        print(full_str)
        self.file_objects['status'].write(full_str + '\n')
        self.file_objects['status'].flush()

    def write_heater_file(self):
        # heater readings
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")

        heater_channels = ["a1_u", "a1_r_lead", "a1_r_htr", "a2_u", "a2_r_lead",
                           "a2_r_htr", "htr", "htr_range"]
        data = {}
        for h_ch in heater_channels:
            data[h_ch] = '%.5E' % float(random.randint(0, 1000000) / 100000)

        data_str = ''
        for ch in heater_channels:
            data_str += f",{ch},{data[ch]}"
        full_str = f"{time_str}{data_str}"

        print(full_str)
        self.file_objects['heaters'].write(full_str + '\n')
        self.file_objects['heaters'].flush()


if __name__ == '__main__':
    interval = 1
    countdown = 10

    simulator = LogSimulator()

    while True:
        simulator.write_thermometer_files()

        # Write every ten seconds
        countdown -= 1
        if countdown == 0:
            countdown = 10
            simulator.write_flowmeter_file()
            simulator.write_maxigauge_file()
            simulator.write_channel_file()
            simulator.write_status_file()

        time.sleep(interval)
