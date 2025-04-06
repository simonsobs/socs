import argparse
import time
import traceback

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.wiregrid_encoder.drivers import EncoderParser

NUM_ENCODER_TO_PUBLISH = 1000
SEC_ENCODER_TO_PUBLISH = 1
COUNTER_INFO_LENGTH = 100
COUNTS_ON_BELT = 52000
REFERENCE_COUNT_MAX = 2 << 15  # > that of belt on wiregrid (=nominal 52000)


def count2time(counts, t_offset=0.):
    t_array = np.array(counts, dtype=float) - counts[0]
    t_array *= 5.e-9
    t_array += t_offset
    return t_array.tolist()


class WiregridEncoderAgent:
    """ Agent to record the wiregrid rotary-encoder data.
    The encoder signal and IRIG timing signal is read
    by a BeagleBoneBlack (BBB).
    The BBB sends the data to this PC via Ethernet.

    Args:
        bbport(int): Port number of the PC
                     determined in the script running in the BBB.
    """

    def __init__(self, agent_obj, bbport=50007):

        self.agent: ocs_agent.OCSAgent = agent_obj
        self.log = agent_obj.log
        self.lock = TimeoutLock()

        self.take_data = False

        self.bbport = bbport

        # Stored previous rising_edge_count and irig_time
        self.rising_edge_count = 0
        self.irig_time = 0

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'wgencoder_rough', record=True,
            agg_params=agg_params, buffer_time=0.5)

        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed(
            'wgencoder_full', record=True, agg_params=agg_params)

        self.parser = EncoderParser(beaglebone_port=self.bbport)

    def acq(self, session, params=None):
        """acq()

        **Process** - Run data acquisition.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {'fields': {
                    'irig_data': {
                        'last_updated': timestamp,
                        'irig_time': computer unix time
                                     in receiving the IRIG packet,
                        'rising_edge_count': PRU clock (BBB clock) count,
                        'edge_diff': Difference of PRU clock
                                     from the previous IRIG data,
                        'irig_sec': IRIG second,
                        'irig_min': IRIG minuite,
                        'irig_hour': IRIG hour,
                        'irig_day': IRIG Day,
                        'irig_year': IRIG Year
                        },
                    'encoder_data': {
                        'last_updated': timestamp,
                        'quadrature' (list): quadrature encoder signals,
                        'pru_clock' (list): PRU clock (Beaglebone clock) ,
                        'reference_degree' (list):
                            Encoder rotation position [deg.],
                        'error' (list): Encoder error flags
                        },
                    },
                'timestamp':
                    timestamp when it updates the irig or encoder data
                }
        """

        time_encoder_published = 0
        quad_data = []
        pru_clock = []
        ref_count = []
        error_flag = []
        received_time_list = []

        dclock = []
        dcount = []
        rot_speed = []

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not start acq because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock.'

            self.take_data = True
            # Initialize data containers
            session.data = {'fields': {'irig_data': {}, 'encoder_data': {},
                            'timestamp': 0}}
            irig_rdata = {'timestamp': 0,
                          'block_name': 'wgencoder_irig',
                          'data': {
                              'irig_time': 0,
                              'rising_edge_count': 0,
                              'edge_diff': 0,
                              'irig_sec': 0,
                              'irig_min': 0,
                              'irig_hour': 0,
                              'irig_day': 0,
                              'irig_year': 0,
                          }
                          }
            irig_last_updated = 0
            irig_fdata = {'timestamps': [],
                          'block_name': 'wgencoder_irig_raw',
                          'data': {}
                          }
            enc_rdata = {
                'timestamps': [],
                'block_name': 'wgencoder_rough',
                'data': {}
            }
            enc_last_updated = 0
            enc_fdata = {
                'timestamps': [],
                'block_name': 'wgencoder_full',
                'data': {}
            }

            # Loop
            while self.take_data:

                try:
                    self.parser.grab_and_parse_data()
                except Exception as e:
                    self.log.warn('ERROR in grab_and_parse_data() : error={}'
                                  .format(e))
                    with open('parse_error.log', 'a') as f:
                        traceback.print_exc(file=f)

                # Check current time
                current_time = time.time()

                # IRIG part mainly takes over CHWP scripts by H.Nishino
                if len(self.parser.irig_queue):
                    irig_last_updated = current_time
                    irig_data = self.parser.irig_queue.popleft()

                    rising_edge_count = irig_data[0]
                    irig_time = irig_data[1]
                    irig_info = irig_data[2]
                    synch_pulse_clock_counts = irig_data[3]
                    sys_time = irig_data[4]

                    irig_rdata['timestamp'] = sys_time
                    irig_rdata['data']['irig_time'] = irig_time
                    irig_rdata['data']['rising_edge_count'] = rising_edge_count
                    irig_rdata['data']['edge_diff']\
                        = rising_edge_count - self.rising_edge_count
                    irig_rdata['data']['irig_sec']\
                        = self.parser.de_irig(irig_info[0], 1)
                    irig_rdata['data']['irig_min']\
                        = self.parser.de_irig(irig_info[1], 0)
                    irig_rdata['data']['irig_hour']\
                        = self.parser.de_irig(irig_info[2], 0)
                    irig_rdata['data']['irig_day']\
                        = self.parser.de_irig(irig_info[3], 0)\
                        + self.parser.de_irig(irig_info[4], 0) * 100
                    irig_rdata['data']['irig_year']\
                        = self.parser.de_irig(irig_info[5], 0)

                    # Beagleboneblack clock frequency measured by IRIG
                    if self.rising_edge_count > 0 and irig_time > 0:
                        bbb_clock_freq =\
                            float(rising_edge_count - self.rising_edge_count)\
                            / (irig_time - self.irig_time)
                    else:
                        bbb_clock_freq = 0.
                    irig_rdata['data']['bbb_clock_freq'] = bbb_clock_freq

                    self.agent.publish_to_feed('wgencoder_rough', irig_rdata)

                    self.rising_edge_count = rising_edge_count
                    self.irig_time = irig_time

                    # saving clock counts for every refernce edge
                    # and every irig bit info
                    # 0.09: time difference in seconds b/w reference marker and
                    #       the first index marker
                    irig_fdata['timestamps'] =\
                        sys_time + 0.09 + np.arange(10) * 0.1
                    irig_fdata['data']['irig_synch_pulse_clock_time'] =\
                        list(irig_time + 0.09 + np.arange(10) * 0.1)
                    irig_fdata['data']['irig_synch_pulse_clock_counts'] =\
                        synch_pulse_clock_counts
                    irig_fdata['data']['irig_info'] = list(irig_info)
                    self.agent.publish_to_feed('wgencoder_full', irig_fdata)
                    # End of IRIG case

                if len(self.parser.encoder_queue):
                    enc_last_updated = current_time
                    encoder_data = self.parser.encoder_queue.popleft()

                    quad_data += encoder_data[0].tolist()
                    pru_clock += encoder_data[1].tolist()
                    ref_count +=\
                        (encoder_data[2] % REFERENCE_COUNT_MAX).tolist()
                    error_flag += encoder_data[3].tolist()
                    received_time_list.append(encoder_data[4])

                    dclock.append(
                        (encoder_data[1][-1] - encoder_data[1][0]) * 5e-9)
                    if (dclock[-1] > 0.)\
                       and (ref_count[-COUNTER_INFO_LENGTH] > ref_count[-1]):
                        dcount.append(
                            (ref_count[-1]
                             + COUNTS_ON_BELT
                             - ref_count[-COUNTER_INFO_LENGTH])
                            / COUNTS_ON_BELT)
                    else:
                        dcount.append(
                            (ref_count[-1]
                             - ref_count[-COUNTER_INFO_LENGTH])
                            / COUNTS_ON_BELT)

                    rot_speed.append(dcount[-1] / dclock[-1])

                    if len(pru_clock) > NUM_ENCODER_TO_PUBLISH \
                        or (len(pru_clock)
                            and (current_time - time_encoder_published)
                            > SEC_ENCODER_TO_PUBLISH):
                        enc_rdata['timestamps'] = received_time_list
                        enc_rdata['data']['quadrature'] =\
                            quad_data[::COUNTER_INFO_LENGTH]
                        enc_rdata['data']['pru_clock'] =\
                            pru_clock[::COUNTER_INFO_LENGTH]
                        enc_rdata['data']['reference_degree'] =\
                            (np.array(ref_count)[::COUNTER_INFO_LENGTH]
                             * 360 / COUNTS_ON_BELT).tolist()
                        enc_rdata['data']['error'] =\
                            error_flag[::COUNTER_INFO_LENGTH]

                        enc_rdata['data']['rotation_speed'] = rot_speed  # Hz
                        self.agent.publish_to_feed(
                            'wgencoder_rough', enc_rdata)
                        enc_fdata['timestamps'] =\
                            count2time(pru_clock, received_time_list[0])
                        enc_fdata['data']['quadrature'] = quad_data
                        enc_fdata['data']['pru_clock'] = pru_clock
                        enc_fdata['data']['reference_count'] = ref_count
                        enc_fdata['data']['error'] = error_flag
                        self.agent.publish_to_feed('wgencoder_full', enc_fdata)

                        quad_data = []
                        pru_clock = []
                        ref_count = []
                        error_flag = []
                        received_time_list = []

                        dclock = []
                        dcount = []
                        rot_speed = []

                        time_encoder_published = current_time

                        # End of filling encoder data
                    # End of encoder case

                # store session.data
                irig_field_dict = {
                    'last_updated': irig_last_updated,
                    'irig_time': irig_rdata['data']['irig_time'],
                    'rising_edge_count':
                        irig_rdata['data']['rising_edge_count'],
                    'edge_diff': irig_rdata['data']['edge_diff'],
                    'irig_sec': irig_rdata['data']['irig_sec'],
                    'irig_min': irig_rdata['data']['irig_min'],
                    'irig_hour': irig_rdata['data']['irig_hour'],
                    'irig_day': irig_rdata['data']['irig_day'],
                    'irig_year': irig_rdata['data']['irig_year']
                }
                enc_field_dict = {
                    'last_updated': enc_last_updated,
                    'quadrature': enc_rdata['data']['quadrature'],
                    'pru_clock': enc_rdata['data']['pru_clock'],
                    'reference_degree':
                        enc_rdata['data']['reference_degree'],
                    'error': enc_rdata['data']['error']
                }
                session.data['timestamp'] = current_time
                session.data['fields']['irig_data'] = irig_field_dict
                session.data['fields']['encoder_data'] = enc_field_dict
                # End of loop
            # End of lock acquiring

        self.agent.feeds['wgencoder_rough'].flush_buffer()
        # This buffer (full data) has huge data size.
        self.agent.feeds['wgencoder_full'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop takeing data.'
        else:
            return False, 'acq is not currently running.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', dest='port',
                        type=int, default=50007,
                        help='Port of the beaglebone '
                             'running wiregrid encoder DAQ')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='WiregridEncoderAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    wg_encoder_agent = WiregridEncoderAgent(agent, bbport=args.port)

    agent.register_process('acq',
                           wg_encoder_agent.acq,
                           wg_encoder_agent.stop_acq,
                           startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
