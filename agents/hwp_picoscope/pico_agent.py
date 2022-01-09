import numpy as np
import time, datetime
import sys, os
import argparse
import warnings
import txaio
txaio.use_twisted()

import class_ps3000a as ps 

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class PicoAgent:
    def __init__(self, agent):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        # Registers Temperature and Voltage feeds
        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('sensors', record=True, agg_params=agg_params)
        agg_params = {'frame_length': 60}
        self.agent.register_feed('downsampled_sensors', record=True, agg_params=agg_params)

    # Task functions.
    def init_picoscope(self, session, params=None):
        if self.initialized:
            return True, "Already Initialized Module"
        
        self.initialized = True

        self.agent.start('acq')

        return True, 'Picoscope initialized.'

    def start_acq(self, session, params=None):
        """acq(params=None)
        Method to start data acquisition process.
        The most recent data collected is stored in session.data in the
        structure::
        """
        if params is None:
            params = {}

        session.set_status('running')
        self.take_data = True

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        self.dev.close()
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'
    
    def run_single(self, session, params):
        #run_single(Npoints, samplefreq, biasfreq)

        Npoints = int(params['Npoints'])
        samplefreq = float(params['samplefreq'])
        biasfreq = float(params['biasfreq'])
        
        with self.lock.acquire_timeout(0, job='run_single') as acquired:
            if not acquired:
                self.log.warn("Could not start run_single because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

        
        current_time = time.time()
        
        pico = ps.ps3000a(Npoints, samplefreq)
        pico.SigGenSingle(biasfreq)
        pico.SetScopeAll()
        pico.SetBufferAll()
        pico.set_digital_port()
        pico.set_digital_buffer()
        pico.Stream_AD()
        t, A, B, C, D = pico.get_value()
        Digital = pico.get_digital_values_simple()
        info = pico.info
        pico.close()
        
        ## save downsampled data and metadata.
        data_downsampled = {
            'block_name': 'sens',
            'timestamp': current_time, 
            'data': {}
        }
        for key, value in info.items():
            data_downsampled['data'][key] = value 
        data_downsampled['data']['ch_A_ave'] = np.average(A) 
        data_downsampled['data']['ch_B_ave'] = np.average(B)
        data_downsampled['data']['ch_C_ave'] = np.average(C)
        data_downsampled['data']['ch_D_ave'] = np.average(D)
        data_downsampled['data']['ch_A_std'] = np.std(A) 
        data_downsampled['data']['ch_B_std'] = np.std(B)
        data_downsampled['data']['ch_C_std'] = np.std(C)
        data_downsampled['data']['ch_D_std'] = np.std(D)
        data_downsampled['data']['ch_B_Acos'] = np.average(np.array(A)*np.array(B))
        data_downsampled['data']['ch_C_Acos'] = np.average(np.array(A)*np.array(C))
        data_downsampled['data']['ch_D_Acos'] = np.average(np.array(A)*np.array(D))
        #approximated sin
        nroll = 6 
        data_downsampled['data']['ch_B_Asin'] = np.average(np.roll(A,nroll)*np.array(B))
        data_downsampled['data']['ch_C_Asin'] = np.average(np.roll(A,nroll)*np.array(C))
        data_downsampled['data']['ch_D_Asin'] = np.average(np.roll(A,nroll)*np.array(D))
        for i, ch in enumerate(Digital): 
            ch = np.array([int(d) for d in ch])
            rising_edge = list(np.flatnonzero((ch[:-1] < .5) & (ch[1:] > .5))+1)
            falling_edge = list(np.flatnonzero((ch[:-1] > .5) & (ch[1:] < .5))+1)
            #data_downsampled['data']['ch_%d_rise'%i] = rising_edge 
            #data_downsampled['data']['ch_%d_fall'%i] = falling_edge 
            data_downsampled['data']['ch_%d_rate'%i] = (len(rising_edge or [])+len(falling_edge or []))/pico.info['length_sec']  
        self.agent.publish_to_feed('downsampled_sensors', data_downsampled)
        print(data_downsampled['data'])
        
        ## save raw data
        ## split data and publish one by one 
        Np = 10000
        for i in np.arange(int(np.ceil(len(t)/Np))):
            data = {
                'block_name': 'sens',
                'data': {}
            }
            t_split = list(t[i*Np:(i+1)*Np])
            A_split = list(A[i*Np:(i+1)*Np])
            B_split = list(B[i*Np:(i+1)*Np])
            C_split = list(C[i*Np:(i+1)*Np])
            D_split = list(D[i*Np:(i+1)*Np])
            
            data['data']['timestamp'] = t_split 
            data['data']['ch_A'] = A_split
            data['data']['ch_B'] = B_split
            data['data']['ch_C'] = C_split 
            data['data']['ch_D'] = D_split 
            data['timestamps'] = [current_time+i/samplefreq for i in range(len(t_split))] 
            for j, ch in enumerate(Digital): 
                ch = [int(d) for d in ch]
                data['data']['ch_%d'%j] = ch[i*Np:(i+1)*Np]

            self.log.debug('publish {}/{}. {}'.format(i, int(np.ceil(len(t)/Np)), len(t_split)))
            self.agent.publish_to_feed('sensors', data)
            self.agent.feeds['sensors'].flush_buffer()
        
        return True, 'Single acquisition exited cleanly.'
        
    def sig_test(self, session, params):
        #sig_test(freq, duration)
        freq = params['freq']
        duration = params['duration']
        pico = ps.ps3000a(1, 1)
        pico.SigGenSingle(freq)
        time.sleep(duration)
        pico.close()
        return True, 'Signal generator test is done.'

def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    return parser

def main():
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    p = site_config.add_arguments()
    parser = make_parser(parser=p)
    
    args = parser.parse_args()
    site_config.reparse_args(args, 'PicoAgent')

    agent, runner = ocs_agent.init_site_agent(args)

    pa = PicoAgent(agent)
    agent.register_task('init_picoscope', pa.init_picoscope, startup = True)
    agent.register_task('run_single', pa.run_single)
    agent.register_task('sig_test', pa.sig_test)
    agent.register_process('acq', pa.start_acq, pa.stop_acq)

    runner.run(agent, auto_reconnect=True)

if __name__ == '__main__':
    main()
