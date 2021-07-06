import socket
import struct
import select
import time
import numpy as np
from collections import deque

## should be consistent with the software on beaglebone
COUNTER_INFO_LENGTH = 100
# header, quad, clock, clock_overflow, refcount, error
COUNTER_PACKET_SIZE = 4 + 4 * 5 * COUNTER_INFO_LENGTH
#IRIG_PACKET_SIZE = 132

class EncoderParser:

    def __init__(self, beaglebone_port=50007, read_chunk_size=8192):

        self.encoder_queue = deque()
        #self.irig_queue = deque()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('',beaglebone_port))

        self.data = ''
        self.read_chunk_size = read_chunk_size

    def check_once(self):

        ready = select.select([self.sock], [], [], 2)
        if ready[0]:
            self.data = self.sock.recv(self.read_chunk_size)

        if not self.check_data_length(0, 4):
            self.log.error('Error 0')

        header = self.data[0:4]
        header = struct.unpack('<I', header)[0]

        if header == 0x1eaf:
            if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                self.log.error('Error 1')
            self.parse_counter_info(self.data[4: COUNTER_PACKET_SIZE])
            pass

        res_bb = self.encoder_queue.popleft()

        print(res_bb)

    def check_data_length(self, start_index, size_of_read):
        if start_index + size_of_read > len(self.data):
            self.data = self.data[start_index:]
            return False # why returning False?
        return True

    def grab_and_parse_data(self):
        while True:
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
                        self.parse_counter_info(self.data[4: COUNTER_PACKET_SIZE])
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

        self.encoder_queue.append((derter[0:COUNTER_INFO_LENGTH], \
                                   derter[COUNTER_INFO_LENGTH:2*COUNTER_INFO_LENGTH] \
                                + (derter[2*COUNTER_INFO_LENGTH:3*COUNTER_INFO_LENGTH] << 32), \
                                   derter[3*COUNTER_INFO_LENGTH:4*COUNTER_INFO_LENGTH], \
                                   derter[4*COUNTER_INFO_LENGTH:5*COUNTER_INFO_LENGTH], \
                                   time.time()))

    def __del__(self):
        self.sock.close()

if __name__=='__main__':
    test = EncoderParser()
    test.check_once()
    del test
    pass
