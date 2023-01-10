import argparse
import os
import time

import numpy as np
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

txaio.use_twisted()

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    import socs.agents.hwp_picoscope.drivers.class_ps3000a as ps


class PicoAgent:
    """Agent for interfacing with a Picoscope 3403D MSO device.

    Args:
        agent (ocs.ocs_agent.OCSAgent): Instantiated OCSAgent class for this
            Agent
    """

    def __init__(self, agent):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        # Registers raw data and down sampled data feeds
        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('sensors', record=True, agg_params=agg_params)
        agg_params = {'frame_length': 60}
        self.agent.register_feed('downsampled_sensors', record=True, agg_params=agg_params)

    # Task functions.
    @ocs_agent.param('Npoints', default=10000, type=int)
    @ocs_agent.param('samplefreq', default=3.6e6, type=float)
    @ocs_agent.param('biasfreq', default=150e3, type=float)
    def run_single(self, session, params):
        """run_single(Npoints=10000, samplefreq=3.6e6, biasfreq=150e3)

           **Task** - Bias LC probes and perform DAQ.

           Parameters:
               Npoints (int): Number of points to measure
               samplefreq (float): sampling frequency (Hz), typically 24*biasfreq
               biasfrequency (float): LC probe bias frequency (Hz)

        """
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

        # save downsampled data and metadata.
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
        data_downsampled['data']['ch_B_Acos'] = np.average(np.array(A) * np.array(B))
        data_downsampled['data']['ch_C_Acos'] = np.average(np.array(A) * np.array(C))
        data_downsampled['data']['ch_D_Acos'] = np.average(np.array(A) * np.array(D))
        # approximated sin
        nroll = 6
        data_downsampled['data']['ch_B_Asin'] = np.average(np.roll(A, nroll) * np.array(B))
        data_downsampled['data']['ch_C_Asin'] = np.average(np.roll(A, nroll) * np.array(C))
        data_downsampled['data']['ch_D_Asin'] = np.average(np.roll(A, nroll) * np.array(D))
        for i, ch in enumerate(Digital):
            ch = np.array([int(d) for d in ch])
            rising_edge = list(np.flatnonzero((ch[:-1] < .5) & (ch[1:] > .5)) + 1)
            falling_edge = list(np.flatnonzero((ch[:-1] > .5) & (ch[1:] < .5)) + 1)
            # data_downsampled['data']['ch_%d_rise'%i] = rising_edge
            # data_downsampled['data']['ch_%d_fall'%i] = falling_edge
            data_downsampled['data']['ch_%d_rate' % i] = (len(rising_edge or []) + len(falling_edge or [])) / pico.info['length_sec']
        self.agent.publish_to_feed('downsampled_sensors', data_downsampled)
        print(data_downsampled['data'])

        # save raw data
        # split data and publish one by one
        Np = 10000
        for i in np.arange(int(np.ceil(len(t) / Np))):
            data = {
                'block_name': 'sens',
                'data': {}
            }
            t_split = list(t[i * Np:(i + 1) * Np])
            A_split = list(A[i * Np:(i + 1) * Np])
            B_split = list(B[i * Np:(i + 1) * Np])
            C_split = list(C[i * Np:(i + 1) * Np])
            D_split = list(D[i * Np:(i + 1) * Np])

            data['data']['timestamp'] = t_split
            data['data']['ch_A'] = A_split
            data['data']['ch_B'] = B_split
            data['data']['ch_C'] = C_split
            data['data']['ch_D'] = D_split
            data['timestamps'] = [current_time + i / samplefreq for i in range(len(t_split))]
            for j, ch in enumerate(Digital):
                ch = [int(d) for d in ch]
                data['data']['ch_%d' % j] = ch[i * Np:(i + 1) * Np]

            self.log.debug('publish {}/{}. {}'.format(i, int(np.ceil(len(t) / Np)), len(t_split)))
            self.agent.publish_to_feed('sensors', data)
            self.agent.feeds['sensors'].flush_buffer()

        return True, 'Single acquisition exited cleanly.'

    @ocs_agent.param('freq', default=10., type=float)
    @ocs_agent.param('duration', default=1., type=float)
    def sig_test(self, session, params):
        """sig_test(freq=10., duration=1.)

           **Task** - For debug and test.

           Parameters:
               freq (float): bias frequency (Hz)
               duration (float): bias duration time (sec)

        """
        with self.lock.acquire_timeout(0, job='sig_test') as acquired:
            if not acquired:
                self.log.warn("Could not start sig_test because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

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

    # Fix me after correcting "priviledged true"
    # pgroup = parser.add_argument_group('Agent Options')
    # pgroup.add_argument('--port', type=stri, help="Path to USB node for the picoscope.")
    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='PicoAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    pa = PicoAgent(agent)
    agent.register_task('run_single', pa.run_single)
    agent.register_task('sig_test', pa.sig_test)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
