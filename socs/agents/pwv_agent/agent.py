import numpy as np
import requests
from numpy import random
import os
from os import environ
import datetime
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
#from twisted.internet.defer import inlineCallbacks
#from autobahn.twisted.util import sleep as dsleep
import argparse
import txaio

# temporary until Agent is updated to read from API
#from api.pwv_web import read_data_from_textfile

def _julian_day_year_to_unixtime(day, year):
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
    """Read the UCSC PWV data files.

    Args:
        filename (str): Path to file
        year (int): Year the data is from

    Returns:
        tuple: (pwv, timestamp)

    """
    with open(filename, 'r') as f:
        i = 0
        for l in f.readlines():
            if i == 0:
                pass  # skip header
            else:
                line = l.strip().split()
                timestamp = _julian_day_year_to_unixtime(float(line[0]), year)

                pwv = float(line[1])

                _data = (pwv, timestamp)

            i += 1
        return _data

class PWVAgent:
    """Monitor the PWV flask server.

    Parameters
    ----------
    address (str): address to the pwv web api on the network
    year (int): year for the corresponding Julian Day
    """
    def __init__(self, agent, url, year):
        self.agent = agent
        self.url = url
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
    
    def start_acq(self, session, params=None):
        """
        PROCESS: Acquire data and write to feed

        Args:
            address (str): address to the pwv web api on the network
            year (int): year for the corresponding Julian Day

        """
        while True:
            r = requests.get(self.url)
            data= r.json()
            last_pwv = data['pwv']
            last_timestamp = data['timestamp']

            pwvs = {'block_name': 'pwvs',
                    'timestamp': last_timestamp,
                    'data': {'pwv': last_pwv}
                    }

            if self.last_published_reading is not None:
                if last_timestamp > self.last_published_reading[0]:
                    self.agent.publish_to_feed('pwvs', pwvs)
                    self.last_published_reading = (last_pwv, last_timestamp)
            else:
                self.agent.publish_to_feed('pwvs', pwvs)
                self.last_published_reading = (last_pwv, last_timestamp)

    def _stop_acq(self):
        ok = False
        with self.lock:
            if self.job == 'acq':
                self.job = '!acq'
                ok = True
            return (ok, {True: 'Requested process stop.', False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--url", type=str, help="url for PWV flask server")
    pgroup.add_argument("--year", type=int, help="year for Julian Day PWV measurement")
    return parser_in

def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))
    
    parser = add_agent_args()
    args = site_config.parse_args(agent_class='PWVAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    pwv_agent = PWVAgent(agent, args.url, args.year)

    agent.register_process('acq', pwv_agent.start_acq, pwv_agent._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)

if __name__ == "__main__":
    main()

# TODO: add docstrings to class for parameters
# TODO: add test mode to acq process
