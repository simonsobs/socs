import os
import time
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

NUM_ENCODER_TO_PUBLISH = 1000
SEC_ENCODER_TO_PUBLISH = 2

COUNTER_INFO_LENGTH = 100

COUNTS_ON_BELT = 52000
REFERENCE_COUNT_MAX = 2 << 15 # > that of belt on wiregrid (=nominal 52000)

SLEEP=0.1
#SLEEP=1

class WGEncoderAgent:

    def __init__(self, agent_obj, bbport=50007):

        self.agent: ocs_agent.OCSAgent = agent_obj
        self.log = agent_obj.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        self.bbport = bbport

        self.rising_edge_count = 0
        self.irig_time = 0

        agg_params = {'frame_length': 60}
        self.agent.register_feed('WGEncoder_rough', record=True, agg_params=agg_params, buffer_time=0.5)

        #agg_params = {'frame_length': 60, 'exclude_influx': True}
        #self.agent.register_feed('WGEncoder_full', record=True, agg_params=agg_params)

        self.parser = EncoderParser(beaglebone_port=self.bbport)

    def start_acq(self, session, params=None):
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

                #loop_start = time.time()

                try:
                    self.parser.grab_and_parse_data()
                except Exception as e:
                    self.log.warn('ERROR in grab_and_parse_data() : error={}'.format(e))
                    with open('parse_error.log', 'a') as f:
                        traceback.print_exc(file=f)
                        pass
                    pass


                if len(self.parser.irig_queue):
                    irig_data = self.parser.irig_queue.popleft()

                    rising_edge_count = irig_data[0]
                    irig_time = irig_data[1]
                    irig_info = irig_data[2]
                    synch_pulse_clock_counts = irig_data[3]
                    sys_time = irig_data[4]

                    irg_rdata = {'timestamp':sys_time, 'block_name':'WGEncoder_irig', 'data':{}}

                    irg_rdata['data']['irig_time'] = irig_time
                    irg_rdata['data']['rising_edge_count'] = rising_edge_count
                    irg_rdata['data']['irig_sec'] = self.parser.de_irig(irig_info[0], 1)
                    irg_rdata['data']['irig_min'] = self.parser.de_irig(irig_info[1], 0)
                    irg_rdata['data']['irig_hour'] = self.parser.de_irig(irig_info[2], 0)
                    irg_rdata['data']['irig_day'] = self.parser.de_irig(irig_info[3], 0) + self.parser.de_irig(irig_info[4], 0) * 100
                    irg_rdata['data']['irig_year'] = self.parser.de_irig(irig_info[5], 0)

                    # Beagleboneblack clock frequency measured by IRIG
                    if self.rising_edge_count > 0 and irig_time > 0:
                        bbb_clock_freq = float(rising_edge_count - self.rising_edge_count) / (irig_time - self.irig_time)
                    else:
                        bbb_clock_freq = 0.
                    irg_rdata['data']['bbb_clock_freq'] = bbb_clock_freq

                    self.agent.publish_to_feed('WGEncoder_rough', irg_rdata)
                    self.rising_edge_count = rising_edge_count
                    self.irig_time = irig_time

                    # saving clock counts for every refernce edge and every irig bit info
                    irg_fdata = {'timestamps':[], 'block_name':'WGEncoder_irig_raw', 'data':{}}
                    # 0.09: time difference in seconds b/w reference marker and
                    #       the first index marker
                    irg_fdata['timestamps'] = sys_time + 0.09 + np.arange(10) * 0.1
                    irg_fdata['data']['irig_synch_pulse_clock_time'] = list(irig_time + 0.09 + np.arange(10) * 0.1)
                    irg_fdata['data']['irig_synch_pulse_clock_counts'] = synch_pulse_clock_counts
                    irg_fdata['data']['irig_info'] = list(irig_info)
                    #self.agent.publish_to_feed('WGEncoder_full', irg_fdata)
                    pass

                if len(self.parser.encoder_queue):
                    encoder_data = self.parser.encoder_queue.popleft()

                    iter_counts += 1

                    quad_data += encoder_data[0].tolist()
                    pru_clock += encoder_data[1].tolist()
                    ref_count += (encoder_data[2]%REFERENCE_COUNT_MAX).tolist()
                    error_flag += encoder_data[3].tolist()
                    received_time_list.append(encoder_data[4])
                    #received_time_list += [encoder_data[4]] * len(pru_clock)

                    current_time = time.time()

                    shared_time = received_time_list[-1]
                    shared_position = ref_count[-1]

                    enc_rdata = {
                        'timestamp': [],
                        'block_name': 'WGEncoder_rough',
                        'data': {'quadrature':[],'pru_clock':[],'reference_count':[],'error':[]}
                    }
                    '''
                    enc_fdata = {
                            'timestamp': [],
                            'block_name': 'WGEncoder_full',
                            'data': {}
                    }
                    '''

                    if len(pru_clock) > NUM_ENCODER_TO_PUBLISH \
                        or (len(pru_clock) and (current_time - time_encoder_published) > SEC_ENCODER_TO_PUBLISH):

                        dclock = (pru_clock[-1] - pru_clock[-COUNTER_INFO_LENGTH])*5e-9

                        if (dclock > 0.) and (ref_count[-COUNTER_INFO_LENGTH] > ref_count[-1]):
                            ddeg = (ref_count[-1] + COUNTS_ON_BELT - ref_count[-COUNTER_INFO_LENGTH])*360/COUNTS_ON_BELT
                            pass
                        else:
                            ddeg = (ref_count[-1] - ref_count[-COUNTER_INFO_LENGTH])*360/COUNTS_ON_BELT
                            pass

                        for data_ind in range(int(len(pru_clock)/COUNTER_INFO_LENGTH)):
                            enc_rdata['timestamp']               = received_time_list[data_ind]# + 5e-6*(data_ind%COUNTER_INFO_LENGTH)
                            enc_rdata['data']['quadrature']      = quad_data[data_ind*COUNTER_INFO_LENGTH]
                            enc_rdata['data']['pru_clock']       = pru_clock[data_ind*COUNTER_INFO_LENGTH]
                            enc_rdata['data']['reference_count'] = ref_count[data_ind*COUNTER_INFO_LENGTH]*360/COUNTS_ON_BELT
                            enc_rdata['data']['error']           = error_flag[data_ind*COUNTER_INFO_LENGTH]

                            enc_rdata['data']['ave_count']       = np.mean(ref_count)
                            enc_rdata['data']['speed']           = ddeg/dclock
                            self.agent.publish_to_feed('WGEncoder_rough', enc_rdata)
                            pass

                        '''
                        enc_fdata['timestamp']                   = received_time_list
                        enc_fdata['data']['quadrature']          = quad_data
                        enc_fdata['data']['pru_clock']           = pru_clock
                        enc_fdata['data']['reference_count']     = ref_count
                        enc_fdata['data']['error']               = error_flag
                        self.agent.publish_to_feed('WGEncoder_full', enc_fdata)

                        with open('feed_log', 'w') as f:
                            f.write(str(iter_counts)+'\n')
                            f.write('current_time:'+str(current_time)+'\n')
                            f.write('pru_clock[0]:'+str(pru_clock[0])+'\n')
                            f.write('feed start at:'+str(loop_start)+'\n')
                            pass
                        '''

                        quad_data = []
                        pru_clock = []
                        ref_count = []
                        error_flag = []
                        received_time_list = []

                        time_encoder_published = current_time

                        time.sleep(SLEEP)
                        pass
                    pass

                with open('/data/wg-data/position.log', 'a') as f:
                    f.write(str(shared_time)+' '+str(shared_position)+'\n')
                    f.flush()
                    pass

                #loop_stop = time.time()
                #with open('loop.log', 'a') as f:
                #    f.write('start at:'+str(loop_start)+', stop at:'+str(loop_stop)+'\n')
                #    pass
                pass

        self.agent.feeds['WGEncoder_rough'].flush_buffer()
        #self.agent.feeds['WGEncoder_full'].flush_buffer()

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
