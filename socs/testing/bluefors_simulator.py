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

    Attributes
    ----------
    log_dir : str
        Path for the directory to write log files to.
    file_objects : dict
        A dictionary with the filenames as keys, and a dict as the value. Each
        sub-dict has the following structure::

            {'file_object': <>,
             'file_type': 'thermometer'}


    """

    def __init__(self, log_dir="./sim/"):
        self.log_dir = log_dir
        self.file_objects = {}
        self.create_file_objects(log_dir=log_dir)

    def create_file_objects(self, log_dir):
        # let's forego log rotation, so just make logs for today and only today
        file_date_str = make_utc_time_string("%y-%m-%d")

        filepath = os.path.join(log_dir, file_date_str,)
        mkdir(filepath)

        thermometer_files = make_therm_file_list([1, 2, 5, 6, 8], file_date_str, filepath)
        for _file in thermometer_files:
            self._create_file(filepath, _file, 'thermometer')

        self._create_file(filepath, f'Flowmeter {file_date_str}.log', 'flowmeter')
        self._create_file(filepath, f'maxigauge {file_date_str}.log', 'maxigauge')
        self._create_file(filepath, f'Channels {file_date_str}.log', 'channel')
        self._create_file(filepath, f'Status_{file_date_str}.log', 'status')
        self._create_file(filepath, f'heaters_{file_date_str}.log', 'heater')

    def _create_file(self, dir_, filename, filetype):
        fullpath = os.path.join(dir_, filename)
        self.file_objects[filename] = {"file_object": open(fullpath, 'a'),
                                       "file_type": filetype}

    def close_all_files(self):
        for k, v in self.file_objects.items():
            v['file_object'].close()
            # print(f"Closed file: {k}")

    def __del__(self):
        self.close_all_files()

    def _get_files_by_type(self, filetype):
        """Get a list of all files of a given type.

        Parameters
        ----------
        filetype : str
            File type to return file objects for.

        Returns
        -------
        files : list
            List of simple dicts with {filename: file_object} if multiple files
            match the type.
        file : dict
            Simple dict with {filename: file_object} that matches the given
            type. Returned if there is only a single type match.

        """
        files = []
        for f, d in self.file_objects.items():
            if isinstance(d, dict):
                type_ = d.get('file_type')
                if type_ == filetype:
                    print(f"{f} matched type {filetype}")
                    files.append({f: d['file_object']})

        if len(files) == 1:
            return files[0]
        else:
            return files

    def _write_single_file(self, file_dict, line):
        """
        Parameters
        ----------
        file_dict : dict
            Dict with {filename: file_object}, as returned by
            self._get_files_by_type().
        line : str
            Line to write to file. A newline character will automatically be
            appended.

        """
        filename = list(file_dict.keys())[0]
        file = file_dict[filename]
        print(f"writing to {filename}")
        print(line)
        file.write(line + '\n')
        file.flush()

    def write_thermometer_files(self):
        # all thermometers share a timestamp, so use a single time_str
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        thermometer_files = self._get_files_by_type('thermometer')
        for file in thermometer_files:
            data_str = random.randint(0, 100) / 100
            full_str = " {time},{data}".format(time=time_str, data=data_str)
            self._write_single_file(file, full_str)

    def write_flowmeter_file(self):
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        data_str = random.randint(0, 100) / 100
        full_str = " {time},{data}".format(time=time_str, data=data_str)

        file = self._get_files_by_type('flowmeter')
        self._write_single_file(file, full_str)

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

        file = self._get_files_by_type('maxigauge')
        self._write_single_file(file, full_str)

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

        file = self._get_files_by_type('channel')
        self._write_single_file(file, full_str)

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

        file = self._get_files_by_type('status')
        self._write_single_file(file, full_str)

    def write_heater_file(self):
        # heater readings
        heater_channels = ["a1_u", "a1_r_lead", "a1_r_htr", "a2_u", "a2_r_lead",
                           "a2_r_htr", "htr", "htr_range"]

        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")

        data = {}
        for h_ch in heater_channels:
            data[h_ch] = '%.5E' % float(random.randint(0, 1000000) / 100000)

        data_str = ''
        for ch in heater_channels:
            data_str += f",{ch},{data[ch]}"
        full_str = f"{time_str}{data_str}"

        file = self._get_files_by_type('heater')
        self._write_single_file(file, full_str)


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
