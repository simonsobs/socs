import os
import time
from typing import Counter
import numpy as np
import argparse

import traceback

from signal_parser import EncoderParser

## Required by OCS
ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock
    pass

NUM_ENCODER_TO_PUBLISH = 5000
SEC_ENCODER_TO_PUBLISH = 10

COUNTER_INFO_LENGTH = 100

REFERENCE_COUNT_MAX = 2 << 15 # > that of belt on wiregrid (=nominal 52000)

class WGEncoderAgent:

    def __init__(self, agent_obj, bbport=50007):

        self.agent: ocs_agent.OCSAgent = agent_obj
        self.log = agent_obj.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        self.bbport = bbport

        #self.rising_edge_count = 0
        #self.irig_time = 0

        agg_params = {'frame_length': 60}
        self.agent.register_feed('WGEncoder_rough', record=True, agg_params=agg_params, buffer_time=0.1)

        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('WGEncoder_full', record=True, agg_params=agg_params)

        self.parser = EncoderParser(beaglebone_port=self.bbport)

    def start_acq(self, session, params):
        time_encoder_published = 0
        quad_data = []
        pru_clock = []
        ref_count = []
        error_flag = []
        received_time_list = []

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn('Could not start acq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock.'

            session.set_status('running')

            self.take_data = True

            current_time = time.time()

            iter_counts = 0

            while self.take_data:
                rdata = {
                        'timestamp': [],
                        'block_name': 'WGEncoder_rough',
                        'data': {}
                }
                fdata = {
                        'timestamp': [],
                        'block_name': 'WGEncoder_full',
                        'data': {}
                }

                try:
                    self.parser.grab_and_parse_data()
                except:
                    with open('parse_log', 'a') as f:
                        traceback.print_exc(file=f)
                        pass
                    pass

                if len(self.parser.encoder_queue):
                    encoder_data = self.parser.encoder_queue.popleft()

                    iter_counts += 1

                    with open('test0', 'w') as f:
                        f.write('test')
                        pass

                    quad_data += encoder_data[0].tolist()
                    pru_clock += encoder_data[1].tolist()
                    ref_count += (encoder_data[2]%REFERENCE_COUNT_MAX).tolist()
                    error_flag += encoder_data[3].tolist()
                    received_time_list.append(encoder_data[4])

                    if len(pru_clock) > NUM_ENCODER_TO_PUBLISH \
                        or (len(pru_clock) and (current_time - time_encoder_published) > SEC_ENCODER_TO_PUBLISH):

                        loop_start = time.time()

                        for data_ind in range(int(len(pru_clock)/COUNTER_INFO_LENGTH)):

                            rdata['timestamp']               = received_time_list[data_ind]# + 5e-6*(data_ind%COUNTER_INFO_LENGTH)
                            rdata['data']['quadrature']      = quad_data[data_ind*COUNTER_INFO_LENGTH]
                            rdata['data']['pru_clock']       = pru_clock[data_ind*COUNTER_INFO_LENGTH]
                            rdata['data']['reference_count'] = ref_count[data_ind*COUNTER_INFO_LENGTH]
                            rdata['data']['error']           = error_flag[data_ind*COUNTER_INFO_LENGTH]

                            self.agent.publish_to_feed('WGEncoder_rough', rdata)
                            pass

                        loop_stop = time.time()

                        fdata['timestamp']                   = received_time_list
                        fdata['data']['quadrature']          = quad_data
                        fdata['data']['pru_clock']           = pru_clock
                        fdata['data']['reference_count']     = ref_count
                        fdata['data']['error']               = error_flag

                        self.agent.publish_to_feed('WGEncoder_full', fdata)

                        with open('feed_log', 'w') as f:
                            f.write(str(iter_counts)+'\n')
                            f.write('current_time:'+str(current_time)+'\n')
                            f.write('pru_clock[0]:'+str(pru_clock[0])+'\n')
                            f.write('loop time:'+str(loop_stop - loop_start)+'\n')
                            pass

                        quad_data = []
                        pru_clock = []
                        ref_count = []
                        error_flag = []
                        received_time_list = []

                        time_encoder_published = current_time

                        current_time = time.time()
                        time.sleep(0.05)
                        pass
                    pass
                pass

        self.agent.feeds['WGEncoder_rough'].flush_buffer()
        self.agent.feeds['WGEncoder_full'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop takeing data.'
        else:
            return False, 'acq is not currently running.'

if __name__=='__main__':
    parser = site_config.add_arguments()
    if parser is None: parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=50007)
    args = parser.parse_args()

    site_config.reparse_args(args, 'WGEncoderAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    wg_encoder_agent = WGEncoderAgent(agent, bbport=args.port)
    agent.register_process('acq', wg_encoder_agent.start_acq, wg_encoder_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
