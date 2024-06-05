#!/usr/bin/env python3
'''OCS agent for stimulator encoder
'''
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.stm_encoder.drivers import (PATH_LOCK, StmEncReader,
                                             get_path_dev)


class StmEncAgent:
    '''OCS agent class for stimulator encoder
    '''

    def __init__(self, agent, path_dev=None, path_lock=PATH_LOCK):
        '''
        Parameters
        ----------
        path_dev : str or pathlib.Path
            Path to the generic-uio device file for str_rd IP.
        path_lock : str or pathlib.Path
            Path to the lockfile.
        '''
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        if path_dev is None:
            self._path_dev = get_path_dev()

        self._dev = StmEncReader(self._path_dev, path_lock, verbose=False)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('stm_enc',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def acq(self, session, params):
        '''Starts acquiring data.
        '''
        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            session.set_status('running')

            self.take_data = True
            session.data = {"fields": {}}

            self._dev.run()

            while self.take_data:
                # Data acquisition
                current_time = time.time()
                data = {'timestamps': [], 'block_name': 'stm_enc', 'data': {}}

                ts_list = []
                en_st_list = []

                while not self._dev.fifo.empty():
                    _d = self._dev.fifo.get()
                    ts_list.append(_d.time.utc)
                    en_st_list.append(_d.state)

                if len(ts_list) != 0:
                    data['timestamps'] = ts_list
                    data['data']['state'] = en_st_list

                    field_dict = {'stm_enc': {'ts': ts_list[-1],
                                              'state': en_st_list[-1]}}

                    session.data['fields'].update(field_dict)

                    self.agent.publish_to_feed('stm_enc', data)
                    session.data.update({'timestamp': current_time})

                time.sleep(0.01)

        self.agent.feeds['stm_enc'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
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

    _ = parser.add_argument_group('Agent Options')

    return parser


def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = make_parser()
    args = site_config.parse_args('StmEncAgent',
                                  parser=parser)
    agent_inst, runner = ocs_agent.init_site_agent(args)

    stm_enc_agent = StmEncAgent(agent_inst)

    agent_inst.register_process(
        'acq',
        stm_enc_agent.acq,
        stm_enc_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
