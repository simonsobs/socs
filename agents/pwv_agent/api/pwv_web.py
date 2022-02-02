import os
import time
import datetime

from flask import Flask, jsonify

app = Flask(__name__)


def julian_day_year_to_unixtime(day, year):
    """
    Convert water vapor radiometer's output Julian Day to unix timestamp.

    Args:
        day (float): day of the year
        year (int):  year for the corresponding Julian Day
    """
    a = datetime.datetime(year, 1, 1) + datetime.timedelta(day-1)
    unixtime = time.mktime(a.timetuple())

    return unixtime


def read_data_from_textfile(filename, year):
    with open(filename, 'r') as f:
        i = 0
        for l in f.readlines():
            if i == 0:
                pass  # skip header
            else:
                line = l.strip().split()
                timestamp = julian_day_year_to_unixtime(float(line[0]), year)

                pwv = float(line[1])

                _data = (pwv, timestamp)

            i += 1
        return _data


@app.route("/")
def get_pwv():
    dir_ = os.getenv("PWV_DATA_DIR")
    pwv, timestamp = read_data_from_textfile(os.path.join(dir_, "PWV_UCSC_2Seg_2021-108.txt"), 2021)

    data = {'timestamp': timestamp,
            'pwv': pwv}

    return jsonify(data)
