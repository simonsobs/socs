import os
import time
import numpy as np
import argparse

from signal_parser import EncoderParser

## Required by OCS
ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock
    pass

NUM_ENCODER_TO_PUBLISH = 5000

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
        self.agent.register_feed('WGEncoder', record=True, agg_params=agg_params, buffer_time=1)

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
                data = {
                        'timestamp': [],
                        'block_name':'WGEncoder_PRU',
                        'data':{}
                        }
                self.parser.grab_and_parse_data()

                encoder_data = self.parser.encoder_queue.popleft()
                
                with open('log0', 'w') as f:
                    f.write(str(quad_data[0:3])+'\n')
                    f.write(str(len(quad_data))+'\n')
                    f.write(str(pru_clock[0:3])+'\n')
                    f.write(str(len(pru_clock))+'\n')
                    pass

                iter_counts += 1

                quad_data += encoder_data[0].tolist()
                pru_clock += encoder_data[1].tolist()
                ref_count += encoder_data[2].tolist()
                error_flag += encoder_data[3].tolist()
                received_time_list.append(encoder_data[4])

                if len(quad_data) > NUM_ENCODER_TO_PUBLISH:
                #if (time.time() - current_time) > 1.:

                    with open('feed_log', 'w') as f:
                        f.write(str(iter_counts)+'\n')
                        f.write(str(current_time)+'\n')
                        f.write(str(pru_clock[0])+'\n')
                        f.write(str(ref_count[0])+'\n')
                        pass

                    for data_ind in range(len(pru_clock)):

                        data['timestamp'] = received_time_list[int(data_ind*0.01)] + 5e-6*(data_ind%100)
                        data['data']['pru_clock'] = pru_clock[data_ind]
                        data['data']['reference_count'] = ref_count[data_ind]

                        self.agent.publish_to_feed('WGEncoder', data)
                        pass

                    #data['timestamp'] = current_time
                    #data['data']['pru_clock'] = pru_clock[0]
                    #data['data']['reference_count'] = ref_count[0]
                    
                    quad_data = []
                    pru_clock = []
                    ref_count = []
                    error_flag = []
                    received_time_list = []

                    time_encoder_published = current_time

                    current_time = time.time()
                    time.sleep(1)
                    pass
                pass

        self.agent.feeds['WGEncoder'].flush_buffer()

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
