#!/usr/bin/env python3
'''dS378 ethernet relay'''
import socket
from enum import IntEnum

GET_STATUS = 0x30, 8
SET_RELAY = 0x31, 1
SET_OUTPUT = 0x32, 1
GET_RELAYS = 0x33, 5
GET_INPUTS = 0x34, 2
GET_ANALOG = 0x35, 14
GET_COUNTERS = 0x36, 8


class RelayStatus(IntEnum):
    '''Relay status'''
    on = 1
    off = 0


class dS378:
    '''dS378 ethernet relay'''

    def __init__(self, ip, port, timeout=10):
        self._com = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._com.connect((ip, port))
        self._com.settimeout(timeout)

    def __del__(self):
        self._com.close()

    def _send(self, msg):
        self._com.send(msg)

    def _send1(self, msg_byte):
        self._send(bytearray([msg_byte]))

    def _recv(self, length):
        return self._com.recv(length)

    def _recv1(self):
        return self._recv(1)[0]

    def get_status(self):
        '''Get status of the dS378 device.

        Returns
        -------
        d_status : dict
            Status information
        '''
        self._send1(GET_STATUS[0])
        ret_bytes = self._recv(GET_STATUS[1])

        d_status = {}
        d_status['module_id'] = ret_bytes[0]
        d_status['firm_ver'] = f'{ret_bytes[1]}.{ret_bytes[2]}'
        d_status['app_ver'] = f'{ret_bytes[3]}.{ret_bytes[4]}'
        d_status['V_sppl'] = ret_bytes[5] / 10
        d_status['T_int'] = int.from_bytes(ret_bytes[6:8], signed=True, byteorder='big') / 10

        return d_status

    def set_relay(self, relay_number, on_off, pulse_time=0):
        '''Turns the relay on/off or pulses it

        Parameters
        ----------
        relay_number : int
            relay_number, 1 -- 8
        on_off : int or RelayStatus
            1: on, 0: off
        pulse_time : int, 32 bit
            See document

        Returns
        -------
        status : int
            0: ACK
            otherwise: NACK
        '''
        assert 1 <= relay_number <= 8
        assert 0 <= pulse_time <= 2**32 - 1
        assert on_off in [0, 1]

        msg = bytearray([SET_RELAY[0], relay_number, on_off])
        msg += pulse_time.to_bytes(4, byteorder='big')
        self._send(msg)

        return self._recv1()

    def set_output(self, io_num, on_off):
        '''Set output on/off

        Parameters
        ----------
        io_num : int, 1 -- 7
            I/O port number
        on_off : int or RelayStatus
            1: on, 0: off
        '''
        assert 1 <= io_num <= 7
        assert on_off in [0, 1]

        msg = bytearray([SET_OUTPUT[0], io_num, on_off])
        self._send(msg)

        return self._recv1()

    def get_relays(self):
        ''' Get relay states

        Returns
        -------
        d_status : list of RelayStatus
        '''

        self._send(bytearray([GET_RELAYS[0], 1]))
        ret_bytes = self._recv(GET_RELAYS[1])

        d_status = [None] * 32
        for i in range(32):
            d_status[i] = RelayStatus((ret_bytes[4 - int(i / 8)] >> (i % 8)) & 1)

        return d_status

    def get_inputs(self):
        ''' Get input states

        Returns
        -------
        d_status : list of RelayStatus
        '''

        self._send(bytearray([GET_INPUTS[0], 1]))
        ret_bytes = self._recv(GET_RELAYS[1])

        d_status = [None] * 7
        for i in range(7):
            d_status[i] = RelayStatus((ret_bytes[1] >> i) & 1)

        return d_status

    def get_analog(self):
        '''Get analog input

        Returns
        -------
        values : list of int
        '''

        self._send1(GET_ANALOG[0])
        ret_bytes = self._recv(GET_ANALOG[1])

        values = [None] * 7
        for i in range(7):
            values[i] = int.from_bytes(ret_bytes[2 * i:2 * i + 2], byteorder='big')

        return values

    def get_counters(self, counter_number):
        '''Get counters

        Parameter
        ---------
        counter_number : int
            counter number. 1 -- 8

        Returns
        -------
        c_current : int
            current counter value
        c_reg : register
            capture register for the counter
        '''

        self._send(bytearray([GET_COUNTERS[0], counter_number]))
        ret_bytes = self._recv(GET_COUNTERS[1])
        c_current = int.from_bytes(ret_bytes[0:4], byteorder='big')
        c_reg = int.from_bytes(ret_bytes[4:8], byteorder='big')

        return c_current, c_reg


def main():
    '''Main function'''
    ds_dev = dS378('192.168.215.241', 17123)
    print(ds_dev.get_status())
    ds_dev.set_relay(7, RelayStatus.off)
    print(ds_dev.get_relays()[:8])
    print(ds_dev.get_analog())
    print(ds_dev.get_inputs())


if __name__ == '__main__':
    main()
