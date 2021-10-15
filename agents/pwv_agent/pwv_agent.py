import numpy as np
from numpy import random
import datetime
import time
import os
from os import environ

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as dsleep
import argparse
import txaio

# For logging
txaio.use_twisted()
LOG = txaio.make_logger()


class pwv_loader:
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


class PWV_Agent:
    def __init__(self, agent, filename, year):
        self.agent = agent
        self.filename = filename
        self.year = year

        self.active = True
        self.log = agent.log
        self.lock = TimeoutLock()
        self.job = None

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('pwvs',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

        self.last_published_reading = None

    def read_data_from_textfile(self, _f, year):
        with open(_f, 'r') as f:
            i = 0
            for l in f.readlines():
                if i == 0:
                    pass  # skip header
                else:
                    line = l.strip().split()
                    timestamp = pwv_loader.julian_day_year_to_unixtime(float(line[0]), self.year)

                    data = float(line[1])

                    _data = (data, timestamp)

                i += 1
            return _data

    def start_acq(self, filename, year):
        """
        PROCESS: Acquire data and write to feed

        Args:
            filename (str): name of PWV text file
            year (int): year for the corresponding Julian Day

        """
        while True:
            last_pwv, last_timestamp = self.read_data_from_textfile(self.filename, self.year)

            pwvs = {'block_name': 'pwvs',
                    'timestamp': last_timestamp,
                    'data': {'pwv': last_pwv}
                    }

            if self.last_published_reading is not None:
                if last_timestamp > self.last_published_reading[0]:
                    self.agent.publish_to_feed('pwvs', pwvs)
                    self.last_published_reading = (last_pwv, last_timestamp)
                    print('if pwvs', pwvs)
            else:
                self.agent.publish_to_feed('pwvs', pwvs)
                self.last_published_reading = (last_pwv, last_timestamp)
                print('else pwvs', pwvs)

    def stop_acq(self):
        ok = False
        with self.lock:
            if self.job == 'acq':
                self.job = '!acq'
                ok = True
            return (ok, {True: 'Requested process stop.', False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--textfile", type=str, help="Filename for PWV textfile")
    pgroup.add_argument("--year", type=int, help="Year for Julian Day in textfile")
    return parser_in


if __name__ == "__main__":
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='PWV_Agent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    pwv_agent = PWV_Agent(agent, args.textfile, args.year)

    agent.register_process('acq', pwv_agent.start_acq, pwv_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
