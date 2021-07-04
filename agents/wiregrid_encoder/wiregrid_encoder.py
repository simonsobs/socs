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

class EncoderParser:

    def __init__(self, beaglebone_port=50007, read_chunk_size=8192):

        self.counter_queue = deque()
        self.irig_queue = deque()

        self.is_start = 1
        self.start_time = [0,0,0] # hours, mins, secs
        self.current_time = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('',beaglebone_port))

        self.data = ''
        self.read_chunk_size = read_chunk_size

        self.log = txaio.make_logger()

    def check_data_length(self, start_index, size_of_read):
        if start_index + size_of_read > len(self.data):
            self.data = self.data[start_index:]
            return False

        return True

    def grab_and_parse_data(self):
        while True:
        #for hoge in range(1):
            ready = select.select([self.sock], [], [], 2)
            if ready[0]:
                data = self.sock.recv(self.read_chunk_size)
                if len(self.data) > 0:
                    self.data += data
                    pass
                else:
                    self.data = data
                    pass

                while True:
                #for fuga in range(1):
                    if not self.check_data_length(0, 4):
                        self.log.error('Error 0')
                        break

                    header = self.data[0:4]
                    header = struct.unpack('<I', header)[0]

                    # 0x1EAF = Encoder Packet
                    # 0xCAFE = IRIG Packet
                    # 0xE12A = Error Packet

                    # Encoder
                    if header == 0x1eaf:
                        if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                            self.log.error('Error 1')
                            break
                        self.parse_counter_info(self.data[4 : COUNTER_PACKET_SIZE])
                        if len(self.data) >= COUNTER_PACKET_SIZE:
                            self.data = self.data[COUNTER_PACKET_SIZE:]
                            pass
                        pass

                    elif header == 0x1234:
                        self.log.error('Recieved timeout packet.')
                        self.data = ''
                        pass
                    else:
                        self.log.error('Bad header')
                        self.data = ''
                        pass

                    if len(self.data) == 0:
                        break
                    pass
                break

    def parse_counter_info(self, data):
        derter = np.array(struct.unpack('<' + 'LLLLL' * COUNTER_INFO_LENGTH, data))

        self.counter_queue.append((derter[0:COUNTER_INFO_LENGTH], \
                                   derter[COUNTER_INFO_LENGTH:2*COUNTER_INFO_LENGTH] \
                                + (derter[2*COUNTER_INFO_LENGTH:3*COUNTER_INFO_LENGTH] << 32), \
                                   derter[3*COUNTER_INFO_LENGTH:4*COUNTER_INFO_LENGTH], \
                                   derter[4*COUNTER_INFO_LENGTH:5*COUNTER_INFO_LENGTH], \
                                   time.time()))

    def __del__(self):
        self.sock.close()

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

                while len(self.parser.counter_queue):
                    counter_data = self.parser.counter_queue.popleft()

                    quad_data += counter_data[0].tolist()
                    pru_clock += counter_data[1].tolist()
                    ref_count += counter_data[2].tolist()
                    error_flag += counter_data[3].tolist()
                    recieved_time_list.append(counter_data[4])

                    ct = time.time()

                    if len(pru_clock) >= NUM_ENCODER_TO_PUBLISH \
                    or (len(pru_clock) and (ct - time_encoder_published) > SEC_ENCODER_TO_PUBLISH):
                        data = {'timestamps':[], 'block_name':'WGEncoder_quad', 'data':{}}
                        data['timestamps'] = received_time_list
                        data['data']['quad'] = quad_data
                        self.agent.publish_to_feed('WGEncoder',data)

                        data = {'timestamps':[], 'block_name':'WGEncoder_PRU', 'data':{}}
                        data['data']['pru_clock'] = pru_clock
                        
                        data['timestamps'] = count2time(pru_clock, recieved_time_list[0])

                        #field_dict = {'hoge': {'A': 'fuga', 'B': 'piyo'}}
                        #session.data['fields'].update(field_dict)

                        self.agent.publish_to_feed('WGEncoder_full',data)

                        #session.data.update({'timestamp': ct})

                        quad_data = []
                        pru_clock = []
                        ref_count = []
                        error_flag = []
                        received_time_list = []

                        time_encoder_publish = ct
                    time.sleep(0.5)

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

    runner.run(agent, auto_reconnect=True)
