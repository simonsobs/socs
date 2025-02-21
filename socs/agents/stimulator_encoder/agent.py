#!/usr/bin/env python3
"""OCS agent for stimulator encoder
"""
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.stimulator_encoder.drivers import (PATH_LOCK, StimEncReader,
                                                    get_path_dev)


class StimEncAgent:
    """OCS agent class for stimulator encoder

    Parameters
    ----------
    path_dev : str or pathlib.Path
        Path to the generic-uio device file for str_rd IP.
    path_lock : str or pathlib.Path
        Path to the lockfile.
    """

    def __init__(self, agent, path_dev=None, path_lock=PATH_LOCK):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        if path_dev is None:
            self._path_dev = get_path_dev()

        self._dev = StimEncReader(self._path_dev, path_lock, verbose=False)

        self.initialized = False

        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('stim_enc',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        agg_params_downsampled = {'frame_length': 60}
        self.agent.register_feed('stim_enc_downsampled',
                                 record=True,
                                 agg_params=agg_params_downsampled,
                                 buffer_time=1)

    def acq(self, session, params):
        """acq()

        **Process** - Start acquiring data.

        Notes
        -----
        An example of the session data::

            >>> response.session['data']

            {'timestamp_tai': 1736541833.679634,
             'state': 1,
             'freq': 10.1,
             'timestamp': 1736541796.779634
            }
        """
        pace_maker = Pacemaker(0.5)

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self.take_data = True
            session.data = {}

            self._dev.run()

            tai_latest = 0.
            en_st_latest = 0
            pulse_count = 0

            time_prev = time.time()
            while self.take_data:
                # Data acquisition
                time_now = time.time()
                data = {'block_name': 'stim_enc', 'data': {}}

                tai_list = []
                ts_list = []
                en_st_list = []

                while not self._dev.fifo.empty():
                    _d = self._dev.fifo.get()
                    tai_list.append(_d.time.tai)
                    ts_list.append(_d.utime)
                    en_st_list.append(_d.state)

                if len(tai_list) != 0:
                    data['timestamps'] = ts_list
                    data['data']['timestamps_tai'] = tai_list
                    data['data']['state'] = en_st_list
                    self.agent.publish_to_feed('stim_enc', data)

                    tai_latest = tai_list[-1]
                    en_st_latest = en_st_list[-1]
                    pulse_count += len(en_st_list)

                # Slow feed for InfluxDB and session.data
                freq = pulse_count / (time_now - time_prev)
                field_dict = {'timestamp_tai': tai_latest,
                              'state': en_st_latest,
                              'freq': freq,
                              'timestamp': time_now}
                session.data.update(field_dict)

                data_downsampled = {'timestamp': time_now,
                                    'block_name': 'stim_enc_downsampled',
                                    'data': {
                                        'timestamps_tai': tai_latest,
                                        'state': en_st_latest,
                                        'freq': freq
                                    }}
                self.agent.publish_to_feed('stim_enc_downsampled',
                                           data_downsampled)
                time_prev = time_now
                pulse_count = 0

                pace_maker.sleep()

        self.agent.feeds['stim_enc'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            self._dev.stop()
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--path-dev', default=None, type=str,
                        help='Path to the device file.')
    pgroup.add_argument('--path-lock', default=PATH_LOCK, type=str,
                        help='Path to the lock file.')

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = make_parser()
    args = site_config.parse_args('StimEncAgent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)

    stim_enc_agent = StimEncAgent(agent_inst)

    agent_inst.register_process(
        'acq',
        stim_enc_agent.acq,
        stim_enc_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
