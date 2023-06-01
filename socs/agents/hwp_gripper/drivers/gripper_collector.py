import errno
import multiprocessing
import select
import socket
import struct

import numpy as np


class GripperCollector(object):
    def __init__(self, pru_port):
        self._read_chunk_size = 2**20
        self.pru_port = pru_port

        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.s.setblocking(False)
        self.s.bind(('', self.pru_port))

        self._data_buffer = b''
        self._timeout_sec = 1

        self.queue = multiprocessing.Queue()
        self._data = ''

        self._endian = '<'
        self._unsigned_long_int_size = 4
        self._unsigned_long_int_str = 'L'
        self._num_overflow_bits = self._unsigned_long_int_size * 8
        self._header_size = self._unsigned_long_int_size
        self._clock_freq = 2e8

        self._timeout_msg = 'CHWP Gripper Timeout'
        self._error_msg = 'CHWP Gripper Error'

        self.limit_state = (0, 0)

        self._define_encoder_packet()
        self._define_limit_packet()
        self._define_timeout_packet()

    def relay_gripper_data(self):
        try:
            ready = select.select([self.s], [], [], self._timeout_sec)
            if ready[0]:
                self._data_buffer += self.s.recv(self._read_chunk_size)
        except socket.error as err:
            if err.errno != errno.EAGAIN:
                raise
            else:
                pass

        if len(self._data_buffer) > 0:
            self.queue.put(obj=self._data_buffer, block=True, timeout=None)
            self._data_buffer = b''

    def process_packets(self):
        approx_size = self.queue.qsize()
        return_dict = {'clock': [], 'state': []}
        detect_limit = 0
        for _ in range(approx_size):
            self._data = self.queue.get(block=True, timeout=None)

            data_len = len(self._data)
            parse_index = 0
            while parse_index < data_len:
                header = self._data[parse_index: parse_index + self._header_size]
                header = struct.unpack(("%s%s" % (
                    self._endian, self._unsigned_long_int_str)), header)[0]

                if header == self._encoder_header:
                    clk, state = self._process_encoder_packet(parse_index)
                    parse_index += self._encoder_packet_size
                    return_dict['clock'].append(clk)
                    return_dict['state'].append(state)
                elif header == self._limit_header:
                    clk, state = self._process_limit_packet(parse_index)
                    parse_index += self._limit_packet_size
                    self.limit_state = (clk, state)
                    detect_limit = 1
                elif header == self._timeout_header:
                    self._process_timeout_packet(parse_index)
                    parse_index += self._timeout_packet_size
                else:
                    raise RuntimeError(
                        ("%s: Bad header: %s" % (self._error_msg, str(header))))

            self._data = ''

        if not detect_limit:
            self.limit_state = (0, 0)

        return_dict['clock'] = np.array(return_dict['clock']).flatten()
        return_dict['state'] = np.array(return_dict['state']).flatten()
        return return_dict

    def _define_encoder_packet(self):
        self._encoder_header = 0xBAD0
        self._encoder_header_units = 1
        self._encoder_header_size = (
            self._encoder_header_units * self._unsigned_long_int_size)
        self._encoder_header_str = (
            self._encoder_header_units * self._unsigned_long_int_str)

        self._encoder_data_length = 120
        self._encoder_data_units = 3 * self._encoder_data_length
        self._encoder_data_size = (
            self._encoder_data_units * self._unsigned_long_int_size)
        self._encoder_data_str = (
            self._encoder_data_units * self._unsigned_long_int_str)

        self._encoder_packet_size = (
            self._encoder_header_size + self._encoder_data_size)

        self._encoder_unpack_str = ("%s%s%s" % (
            self._endian, self._encoder_header_str,
            self._encoder_data_str))
        return

    def _define_limit_packet(self):
        self._limit_header = 0xF00D
        self._limit_header_units = 1
        self._limit_header_size = (
            self._limit_header_units * self._unsigned_long_int_size)
        self._limit_header_str = (
            self._limit_header_units * self._unsigned_long_int_str)

        self._limit_clock_units = 1
        self._limit_clock_size = (
            self._limit_clock_units * self._unsigned_long_int_size)
        self._limit_clock_str = (
            self._limit_clock_units * self._unsigned_long_int_str)

        self._limit_overflow_units = 1
        self._limit_overflow_size = (
            self._limit_overflow_units * self._unsigned_long_int_size)
        self._limit_overflow_str = (
            self._limit_overflow_units * self._unsigned_long_int_str)

        self._limit_data_units = 1
        self._limit_data_size = (
            self._limit_data_units * self._unsigned_long_int_size)
        self._limit_data_str = (
            self._limit_data_units * self._unsigned_long_int_str)

        self._limit_packet_size = (
            self._limit_header_size + self._limit_clock_size
            + self._limit_overflow_size + self._limit_data_size)

        self._limit_unpack_str = ("%s%s%s%s%s" % (
            self._endian, self._limit_header_str,
            self._limit_clock_str, self._limit_overflow_str,
            self._limit_data_str))
        return

    def _define_timeout_packet(self):
        self._encoder_timeout_type = 1

        self._timeout_header = 0x1234
        self._timeout_header_units = 1
        self._timeout_header_size = (
            self._timeout_header_units * self._unsigned_long_int_size)
        self._timeout_header_str = (
            self._timeout_header_units * self._unsigned_long_int_str)

        self._timeout_type_units = 1
        self._timeout_type_size = (
            self._timeout_type_units * self._unsigned_long_int_size)
        self._timeout_type_str = (
            self._timeout_type_units * self._unsigned_long_int_str)

        self._timeout_packet_size = (
            self._timeout_header_size + self._timeout_type_size)

        self._timeout_unpack_str = ("%s%s%s" % (
            self._endian, self._timeout_header_str,
            self._timeout_type_str))
        return

    def _process_encoder_packet(self, parse_index):
        start_ind = parse_index
        end_ind = start_ind + self._encoder_packet_size
        unpacked_data = np.array(struct.unpack(
            self._encoder_unpack_str,
            self._data[start_ind:end_ind]))

        ind1 = 0
        ind2 = ind1 + self._encoder_header_units
        header = unpacked_data[ind1:ind2][0]
        if header != self._encoder_header:
            raise RuntimeError(
                "%s: Encoder header error: 0x%04X" % (
                    self._error_msg, header))

        ind1 = ind2
        ind2 = ind1 + self._encoder_data_length
        clock_data = unpacked_data[ind1:ind2]

        ind1 = ind2
        ind2 = ind1 + self._encoder_data_length
        overflow_data = unpacked_data[ind1:ind2]

        ind1 = ind2
        ind2 = ind1 + self._encoder_data_length
        state = unpacked_data[ind1:ind2]

        clk = clock_data + (overflow_data * 2**self._num_overflow_bits)

        return clk / self._clock_freq, state

    def _process_limit_packet(self, parse_index):
        start_ind = parse_index
        end_ind = start_ind + self._limit_packet_size
        unpacked_data = np.array(struct.unpack(
            self._limit_unpack_str, self._data[start_ind:end_ind]))

        ind1 = 0
        ind2 = ind1 + self._limit_header_units
        header = unpacked_data[ind1:ind2][0]
        if header != self._limit_header:
            raise RuntimeError(
                "%s: Limit header error: 0x%x" % (
                    self._error_msg, header))

        ind1 = ind2
        ind2 = ind1 + self._limit_clock_units
        clock = unpacked_data[ind1:ind2][0]

        ind1 = ind2
        ind2 = ind1 + self._limit_overflow_units
        overflow = unpacked_data[ind1:ind2][0]

        ind1 = ind2
        ind2 = ind1 + self._limit_data_units
        state = unpacked_data[ind1:ind2][0]

        clk = clock + (overflow << self._num_overflow_bits)

        return clk, state

    def _process_timeout_packet(self, parse_index):
        start_ind = parse_index
        end_ind = start_ind + self._timeout_packet_size
        unpacked_data = np.array(struct.unpack(
            self._timeout_unpack_str, self._data[start_ind:end_ind]))

        ind1 = 0
        ind2 = ind1 + self._timeout_header_units
        header = unpacked_data[ind1:ind2]
        if header != self._timeout_header:
            raise RuntimeError("Timeout header error: 0x%x" % (header))

        ind1 = ind2
        ind2 - ind1 + self._timeout_type_size
        timeout_type = unpacked_data[ind1:ind2]
        if timeout_type == self._encoder_timeout_type:
            print("Timeout: no encoder data detected")
        else:
            print("Timeout: unknown type '0x%X'" % (timeout_type))
        return
