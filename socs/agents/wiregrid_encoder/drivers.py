import calendar
import select
import socket
import struct
import time
from collections import deque

import numpy as np
import txaio

txaio.use_twisted()

# should be consistent with the software on beaglebone
COUNTER_INFO_LENGTH = 100
# header, quad, clock[100], clock_overflow[100], refcount[100], error[100]
COUNTER_PACKET_SIZE = 4 + 4 * 5 * COUNTER_INFO_LENGTH
# header, clock, clock_overflow, info[10], synch[10], synch_overflow[10]
IRIG_PACKET_SIZE = 132
# header, type
TIMEOUT_PACKET_SIZE = 8


class EncoderParser:

    def __init__(self, beaglebone_port=50007, read_chunk_size=8192):

        self.encoder_queue = deque()
        self.irig_queue = deque()

        self.is_start = 1
        self.start_time = [0, 0, 0]
        self.current_time = 0

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('', beaglebone_port))

        self.data = ''
        self.read_chunk_size = read_chunk_size

        self.log = txaio.make_logger()

    def check_once(self):

        enc_oncetime = False
        irig_oncetime = False
        checking_start = time.time()
        sampling_timeout = 30

        while True:
            ready = select.select([self.sock], [], [], 2)
            if ready[0]:
                self.data = self.sock.recv(self.read_chunk_size)
            if not self.check_data_length(0, 4):
                self.log.error(
                    'Header data length error in check_once()')
            header = self.data[0:4]
            header = struct.unpack('<I', header)[0]

            if enc_oncetime and irig_oncetime:
                print('---finished taking each data---')
                break
            if header == 0x1eaf and not enc_oncetime:  # Encoder data
                if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                    self.log.error(
                        'Failed to catch the Encoder data')
                self.parse_counter_info(self.data[4: COUNTER_PACKET_SIZE])
                res_bb = self.encoder_queue.popleft()
                print('---Encoder Response---')
                print(res_bb)
                enc_oncetime = True
            elif header == 0xcafe and not irig_oncetime:
                if not self.check_data_length(0, IRIG_PACKET_SIZE):
                    self.log.error(
                        'Failed to catch the IRIG data')
                self.parse_irig_info(self.data[4:IRIG_PACKET_SIZE])
                res_irig = self.irig_queue.popleft()
                print('---IRIG Response---')
                print(res_irig)
                irig_oncetime = True
            else:
                pass

            if time.time() - checking_start > sampling_timeout:
                print('time out')
                break
        # End of check_once()

    def check_data_length(self, start_index, size_of_read):
        if start_index + size_of_read > len(self.data):
            self.data = self.data[start_index:]
            return False
        return True

    def grab_and_parse_data(self):
        while True:
            ready = select.select([self.sock], [], [], 2)
            if ready[0]:
                data = self.sock.recv(self.read_chunk_size)
                if len(self.data) > 0:
                    self.data += data
                else:
                    self.data = data

                while True:
                    if not self.check_data_length(0, 4):
                        self.log.error(
                            'Header data length error in grab_and_parse_data()'
                        )
                        break

                    header = self.data[0:4]
                    header = struct.unpack('<I', header)[0]

                    # 0x1EAF = Encoder Packet
                    # 0xCAFE = IRIG Packet
                    # 0xE12A = Error Packet

                    # Encoder
                    if header == 0x1eaf:
                        if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                            self.log.error(
                                'Failed to catch the Encoder data')
                            break
                        self.parse_counter_info(
                            self.data[4: COUNTER_PACKET_SIZE])
                        if len(self.data) >= COUNTER_PACKET_SIZE:
                            self.data = self.data[COUNTER_PACKET_SIZE:]

                    # IRIG
                    elif header == 0xcafe:
                        if not self.check_data_length(0, IRIG_PACKET_SIZE):
                            self.log.error(
                                'Failed to catch the IRIG data')
                            break
                        self.parse_irig_info(self.data[4: IRIG_PACKET_SIZE])
                        if len(self.data) >= IRIG_PACKET_SIZE:
                            self.data = self.data[IRIG_PACKET_SIZE:]

                    elif header == 0x1234:
                        if not self.check_data_length(0, TIMEOUT_PACKET_SIZE):
                            self.log.error(
                                'Failed to catch the Timeout data')
                            self.data = ''
                            break
                        timeout_type = self.data[4:TIMEOUT_PACKET_SIZE]
                        timeout_type = struct.unpack('<I', timeout_type)[0]
                        if timeout_type == 1:
                            self.log.error('Recieved Encoder timeout packet.')
                        elif timeout_type == 2:
                            self.log.error('Recieved IRIG timeout packet.')
                        else:
                            self.log.error('Recieved timeout packet but '
                                           'timeout-type(={}) is unknown type.'
                                           .format(timeout_type))
                        self.data = ''
                        break
                    else:
                        self.log.error('Bad header')
                        self.data = ''

                    if len(self.data) == 0:
                        break
                break

    def parse_counter_info(self, data):
        derter = np.array(
            struct.unpack('<' + 'LLLLL' * COUNTER_INFO_LENGTH, data))

        self.encoder_queue.append(
            (derter[0:COUNTER_INFO_LENGTH],
             derter[COUNTER_INFO_LENGTH:2 * COUNTER_INFO_LENGTH]
             + (derter[2 * COUNTER_INFO_LENGTH:3 * COUNTER_INFO_LENGTH] << 32),
             derter[3 * COUNTER_INFO_LENGTH:4 * COUNTER_INFO_LENGTH],
             derter[4 * COUNTER_INFO_LENGTH:5 * COUNTER_INFO_LENGTH],
             time.time()))

    def parse_irig_info(self, data):

        unpacked_data = struct.unpack('<' + 'LL' + 'LLL' * 10, data)
        rising_edge_time = unpacked_data[0] + (unpacked_data[1] << 32)
        irig_info = unpacked_data[2:12]
        irig_time = self.pretty_print_irig_info(irig_info, rising_edge_time)
        synch_pulse_clock_times = (np.asarray(unpacked_data[12:22])
                                   + (np.asarray(unpacked_data[22:32]) << 32)
                                   ).tolist()
        self.irig_queue.append((rising_edge_time, irig_time, irig_info,
                                synch_pulse_clock_times, time.time()))

    def pretty_print_irig_info(self, irig_info, edge, print_out=False):

        secs = self.de_irig(irig_info[0], 1)
        mins = self.de_irig(irig_info[1], 0)
        hours = self.de_irig(irig_info[2], 0)
        day = self.de_irig(irig_info[3], 0)\
            + self.de_irig(irig_info[4], 0) * 100
        year = self.de_irig(irig_info[5], 0)

        if self.is_start == 1:
            self.start_time = [hours, mins, secs]
            self.is_start = 0

        if print_out:

            dsecs = secs - self.start_time[2]
            dmins = mins - self.start_time[1]
            dhours = hours - self.start_time[0]

            if dhours < 0:
                dhours = dhours + 24

            if (dmins < 0) or ((dmins == 0) and (dsecs < 0)):
                dmins = dmins + 60
                dhours = dhours - 1

            if dsecs < 0:
                dsecs = dsecs + 60
                dmins = dmins - 1

            print('Current Time:', ('%d:%d:%d' % (hours, mins, secs)),
                  'Run Time', ('%d:%d:%d' % (dhours, dmins, dsecs)),
                  'Clock Count\n', edge)

        try:
            st_time = time.strptime(
                "%d %d %d:%d:%d" % (year, day, hours, mins, secs),
                "%y %j %H:%M:%S")
            self.current_time = calendar.timegm(st_time)
        except ValueError:
            self.log.error(f'Invalid IRIG-B timestamp: '
                           f'{year} {day} {hours} {mins} {secs}')
            self.current_time = -1

        return self.current_time

    def de_irig(self, val, base_shift=0):
        return (
            ((val >> (0 + base_shift)) & 1)
            + ((val >> (1 + base_shift)) & 1) * 2
            + ((val >> (2 + base_shift)) & 1) * 4
            + ((val >> (3 + base_shift)) & 1) * 8
            + ((val >> (5 + base_shift)) & 1) * 10
            + ((val >> (6 + base_shift)) & 1) * 20
            + ((val >> (7 + base_shift)) & 1) * 40
            + ((val >> (8 + base_shift)) & 1) * 80
        )

    def __del__(self):
        self.sock.close()


if __name__ == '__main__':
    test = EncoderParser()
    test.check_once()
    del test
