import os
import time
import numpy as np
import socket
import struct
import calendar
from collections import deque
import select
import txaio
import argparse

txaio.use_twisted()

## Required by OCS
ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock
    pass

## should be consistent with the software on beaglebone
COUNTER_INFO_LENGTH = 100
# header, quad, clock, clock_overflow, refcount, error
COUNTER_PACKET_SIZE = 4 + 4 * 5 * COUNTER_INFO_LENGTH
#IRIG_PACKET_SIZE = 132

NUM_SLITS = 570
NUM_ENCODER_TO_PUBLISH = 500
SEC_ENCODER_TO_PUBLISH = 3
NUM_SUBSAMPLE = 500

def count2time(counts, t_offset=0.):
    t_array = np.array(counts, dtype=float) - counts[0]
    t_array *= 5.e-9
    t_array += t_offset

    return t_array.tolist()

class WGEncoderAgent:

    def __init__(self, agent_obj, port=50007):
        self.active = True
        self.agent = agent_obj
        self.log = agent_obj.log
        self.lock = TimeoutLock()
        self.port = port
        self.take_data = False
        self.initialized = False

        self.rising_edge_count = 0
        self.irig_time = 0

        agg_params = {'frame_length': 60}
        self.agent.register_feed('WGEncoder', record=True, agg_params=agg_params)
        #agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('WGEncoder_full', record=True, agg_params=agg_params)

        self.parser = EncoderParser(beaglebone_port=self.port)

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

            #session.data = {"fields": {}}

            while self.take_data:
                self.parser.grab_and_parse_data()
                data = {'timestamps':[], 'block_name':'WGEncoder_quad', 'data':{}}

                for que_ind in range(len(self.parser.counter_queue)):

                    counter_data = self.parser.counter_queue.popleft()

                    #try:
                    quad_data += counter_data[0].tolist()
                    pru_clock += counter_data[1].tolist()
                    ref_count += counter_data[2].tolist()
                    error_flag += counter_data[3].tolist()
                    received_time_list.append(counter_data[4])
                    #except:
                    #    import traceback
                    #    with open('test_log2', 'w') as f:
                    #        traceback.print_exc(file=f)
                    #        pass
                    #    pass

                    ct = time.time()

                    if len(pru_clock) >= NUM_ENCODER_TO_PUBLISH \
                    or (len(pru_clock) and (ct - time_encoder_published) > SEC_ENCODER_TO_PUBLISH):

                        with open('feed_log', 'a') as f:
                            f.write(str(pru_clock[0])+'\n')
                            pass

                        for data_ind in range(len(pru_clock)):
                            #data['timestamps'] = received_time_list[data_ind]
                            data['data']['pru_clock'] = pru_clock[data_ind]
                            self.agent.publish_to_feed('WGEncoder',data)
                            pass

                            #data = {'timestamps':[], 'block_name':'WGEncoder_PRU', 'data':{}}
                            #data['data']['pru_clock'] = pru_clock

                            #data['timestamps'] = count2time(pru_clock, recieved_time_list[0])

                            #field_dict = {'hoge': {'A': 'fuga', 'B': 'piyo'}}
                            #session.data['fields'].update(field_dict)

                            #self.agent.publish_to_feed('WGEncoder_full',data)

                            #session.data.update({'timestamp': ct})

                        quad_data = []
                        pru_clock = []
                        ref_count = []
                        error_flag = []
                        received_time_list = []

                        time_encoder_published = ct

        self.agent.feeds['WGEncoder'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop takeing data.'

        return False, 'acq is not currently running.'

if __name__=='__main__':
    parser = site_config.add_arguments()
    if parser is None: parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=50007)
    args = parser.parse_args()

    site_config.reparse_args(args, 'WGEncoderAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    wg_encoder_agent = WGEncoderAgent(agent, port=args.port)
    agent.register_process('acq', wg_encoder_agent.start_acq, wg_encoder_agent.stop_acq, startup=True)

    with open('test0', 'w') as f:
        f.write('test0\n')
        pass

    runner.run(agent, auto_reconnect=True)
