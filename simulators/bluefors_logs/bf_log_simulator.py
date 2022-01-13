import sys
import time
import random
import os

from datetime import datetime, timezone


def mkdir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory)


# Rules
# All P/T/R measurements from the 372 share timestamps
# Channels can appear at anytime, or not exist at all, depending on if states have changed
# nothing else shares time stamps, so these are all separate
    # Channels
    # Flowmeter
    # maxigauge


# CH 1, 2, 3, 5, 6, 8
# Channels
# Flowmeter
# maxigauge

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


# main
if __name__ == '__main__':
    interval = 1

    # let's forego log rotation, so just make logs for today and only today
    directory_str = make_utc_time_string("%y-%m-%d")
    mkdir("./sim/%s/"%directory_str)
    file_date_str = make_utc_time_string("%y-%m-%d")

    filepath = "./sim/%s/"%(directory_str)
    thermometer_files = make_therm_file_list([1,2,5,6,8], file_date_str, filepath)
    thermometer_file_objects = {}
    for _file in thermometer_files:
        thermometer_file_objects[_file] = open(_file, 'a')

    flowmeter_file = os.path.join(filepath, f'Flowmeter {file_date_str}.log')
    flowmeter_file_object = open(flowmeter_file, 'a')
    flow_countdown = 10

    maxigauge_file = os.path.join(filepath, f'maxigauge {file_date_str}.log')
    maxigauge_file_object = open(maxigauge_file, 'a')
    pressure_channels = ['CH1', 'CH2', 'CH3', 'CH4', 'CH5', 'CH6']

    channel_state_file = os.path.join(filepath, f'Channels {file_date_str}.log')
    channel_state_file_object = open(channel_state_file, 'a')
    state_channels = ['v11', 'v2', 'v1', 'turbo1', 'v12', 'v3', 'v10',
                      'v14', 'v4', 'v13', 'compressor', 'v15', 'v5', 'hs-still', 'v21', 'v16', 'v6',
                      'scroll1', 'v17', 'v7', 'scroll2', 'v18', 'v8', 'pulsetube', 'v19', 'v20',
                      'v9', 'hs-mc', 'ext']

    status_state_file = os.path.join(filepath, f'Status_{file_date_str}.log')
    status_state_file_object = open(status_state_file, 'a')
    status_channels = ['tc400errorcode', 'tc400ovtempelec', 'tc400ovtemppump',
                       'tc400setspdatt', 'tc400pumpaccel', 'tc400commerr', 'tc400errorcode_2',
                       'tc400ovtempelec_2', 'tc400ovtemppump_2', 'tc400setspdatt_2',
                       'tc400pumpaccel_2', 'tc400commerr_2', 'ctrl_pres', 'cpastate', 'cparun',
                       'cpawarn', 'cpaerr', 'cpatempwi', 'cpatempwo', 'cpatempo', 'cpatemph', 'cpalp',
                       'cpalpa', 'cpahp', 'cpahpa', 'cpadp', 'cpacurrent', 'cpahours', 'cpapscale',
                       'cpatscale', 'cpasn', 'cpamodel']

    heater_file = os.path.join(filepath, f'heaters_{file_date_str}.log')
    heater_file_object = open(heater_file, 'a')
    heater_channels = ["a1_u", "a1_r_lead", "a1_r_htr", "a2_u", "a2_r_lead",
                       "a2_r_htr", "htr", "htr_range"]

    while True:
        # all thermometers share a timestamp, so use a single time_str
        time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
        for k, f in thermometer_file_objects.items():
            print('writing to', k)
            data_str = random.randint(0, 100)/100
            full_str = " {time},{data}".format(time=time_str, data=data_str)
            print(full_str)
            f.write(full_str + '\n')
            f.flush()

        # save every 10 seconds
        flow_countdown -= 1
        if flow_countdown == 0:
            flow_countdown = 10
            # Flow isn't necessarily sync'd to temps so lets not do that
            time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
            print('writing to', k)
            data_str = random.randint(0, 100)/100
            full_str = " {time},{data}".format(time=time_str, data=data_str)
            print(full_str)
            flowmeter_file_object.write(full_str + '\n')
            flowmeter_file_object.flush()

            # maxigauge readings
            time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
            ch1_state = random.randint(0,1)
            data = {}
            for p_ch in pressure_channels:
                data[p_ch] = '%.2E'%float(random.randint(0, 100)/100)

            if ch1_state == 0:
                data['CH1'] = '2.00E-02'
            full_str = f"{time_str},CH1,        ,{ch1_state}, {data['CH1']},0,1,"\
                       f"CH2,       ,1, {data['CH2']},1,1,"\
                       f"CH3,       ,1, {data['CH3']},0,1,"\
                       f"CH4,       ,1, {data['CH4']},0,1,"\
                       f"CH5,       ,1, {data['CH5']},0,1,"\
                       f"CH6,       ,1, {data['CH6']},0,1,"
            print(full_str)
            maxigauge_file_object.write(full_str + '\n')
            maxigauge_file_object.flush()

            # channels
            time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")
            full_str = f"{time_str},1"
            for ch in state_channels:
                random_state = random.randint(0,1)
                full_str += f",{ch},{random_state}"
            print(full_str)
            channel_state_file_object.write(full_str + '\n')
            channel_state_file_object.flush()

            # status readings
            time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")

            data = {}
            for s_ch in status_channels:
                if 'tc400' in s_ch:
                    if 'tc400setspdatt' in s_ch:
                        data[s_ch] = '%.5E' % 1
                    else:
                        data[s_ch] = '%.5E' % 0
                else:
                    data[s_ch] = '%.5E'%float(random.randint(0, 1000000)/100000)
            data_str = ''
            for ch in status_channels:
                data_str += f",{ch},{data[ch]}"
            full_str = f"{time_str}{data_str}"

            print(full_str)
            status_state_file_object.write(full_str + '\n')
            status_state_file_object.flush()

            # heater readings
            time_str = make_utc_time_string("%d-%m-%y,%H:%M:%S")

            data = {}
            for h_ch in heater_channels:
                data[h_ch] = '%.5E'%float(random.randint(0, 1000000)/100000)

            data_str = ''
            for ch in heater_channels:
                data_str += f",{ch},{data[ch]}"
            full_str = f"{time_str}{data_str}"

            print(full_str)
            heater_file_object.write(full_str + '\n')
            heater_file_object.flush()

        time.sleep(interval)
