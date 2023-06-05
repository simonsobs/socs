import datetime
import glob
import os
import time

from flask import Flask, jsonify

app = Flask(__name__)


def _julian_day_year_to_unixtime(day, year):
    """
    Convert water vapor radiometer's output Julian Day to unix timestamp.

    Args:
        day (float): day of the year
        year (int):  year for the corresponding Julian Day
    """
    a = datetime.datetime(year, 1, 1) + datetime.timedelta(day - 1)
    unixtime = time.mktime(a.timetuple())

    return unixtime


def read_data_from_textfile(filename, year):
    """Read the UCSC PWV data files.

    Args:
        filename (str): Path to file
        year (int): Year the data is from

    Returns:
        tuple: (pwv, timestamp)

    """
    with open(filename, 'r') as f:
        i = 0
        for line in f.readlines():
            if i == 0:
                pass  # skip header
            else:
                line = line.strip().split()
                timestamp = _julian_day_year_to_unixtime(float(line[0]), year)

                pwv = float(line[1])

                _data = (pwv, timestamp)

            i += 1
        return _data


def get_latest_pwv_file(data_dir):
    """Get the latest PWV data file.

    This assumes a couple of things:
        - File names all start with "PWV_UCSC", have the ".txt" extension, and
          contain the year they are written.
        - You want this year's data.
        - The latest file is the last file when the list of this year's files
          are sorted.

    Args:
        data_dir (str): The data directory where the PWV data is stored.

    Returns:
        str: The full path to the latest text file containing PWV data.

    """
    year = datetime.datetime.now().year
    files = sorted(glob.glob(os.path.join(data_dir, f"PWV_UCSC*{year}*.txt")))
    return files[-1]


@app.route("/")
def get_pwv():
    dir_ = os.getenv("PWV_DATA_DIR")
    file_ = get_latest_pwv_file(dir_)
    year = int(os.path.basename(file_).replace('-', '_').split('_')[3])
    pwv, timestamp = read_data_from_textfile(file_, year)

    data = {'timestamp': timestamp,
            'pwv': pwv}

    return jsonify(data)


if __name__ == "__main__":
    app.run()
