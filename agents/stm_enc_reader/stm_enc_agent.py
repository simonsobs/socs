#!/usr/bin/env python3
'''OCS agent for stimulator encoder
'''
import time
import os
import txaio

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.agent.stm_enc_reader import StmEncReader, SERVER_IP, SERVER_PORT, LOCK_PATH


class StmEncAgent:
    '''OCS agent class for stimulator encoder
    '''
    def __init__(self, agent, ip=SERVER_IP, port=SERVER_PORT, lockpath=LOCK_PATH):
        '''
        Parameters
        ----------
        ip : str
            IP address
        port : int
            Port number
        lockpath : str
            Path to the lock file
        '''
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self.device = None
        self.ip = ip
        self.port = port
        self.lockpath = lockpath

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('stm_enc',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params):
        '''Starts acquiring data.
        '''
        f_sample = params.get('sampling_frequency', 1)
        sleep_time = 1/f_sample - 0.1
        self.device = StmEncReader(ip_addr=self.ip, port=self.port, lockpath=self.lockpath)

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            session.set_status('running')

            self.take_data = True
            session.data = {"fields": {}}
            self.device.connect()

            while self.take_data:
                # Data acquisition
                current_time = time.time()
                data = {'timestamp':current_time, 'block_name':'encoder', 'data':{}}

                self.device.fill()

                data['data']['ts'] = self.device.ts_latest
                data['data']['state'] = self.device.state_latest

                field_dict = {'stm_enc': {'ts': self.device.ts_latest,
                                          'state': self.device.state_latest}}
                session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('stm_enc', data)
                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['stm_enc'].flush_buffer()

        del self.device
        self.device = None

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'



def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()
    _ = parser.add_argument_group('Agent Options')

    args = site_config.parse_args('StmEncAgent')
    agent_inst, runner = ocs_agent.init_site_agent(args)

    stm_enc_agent = StmEncAgent(agent_inst)

    agent_inst.register_process(
        'acq',
        stm_enc_agent.start_acq,
        stm_enc_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)

if __name__ == '__main__':
    main()
