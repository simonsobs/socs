#!/usr/bin/env python3
"""blh motor driver controller"""

from datetime import datetime, timezone
from time import sleep

import numpy as np
import serial

from socs.agents.orientalmotor_blh.om_comm import (ALMCLR, INIT_CMD, MOVE_BKW,
                                                   MOVE_FWD, STATUS, STOP)

DEV_NAME = '/dev/ttyACM0'
UTC = timezone.utc


def calc_parity(data):
    """Parity calculation"""
    return np.bitwise_xor.reduce([i for i in data])


class BLH:
    """BLH motor driver controller"""

    def __init__(self, port=DEV_NAME):
        self._ser = serial.Serial(port, 9600, timeout=0.1)
        self._packet_index = 0
        self._start_dt = None
        self._connected = False

    def __w(self, data):
        self._ser.write(data)

    def __r(self, length):
        return self._ser.read(length)

    def connect(self):
        """Make connection to BLH"""
        self.__w(b'\x06')
        ret = self.__r(1)
        if ret[0] != 0x86:
            raise Exception('Not connected. Abort.')
        self._connected = True
        self._start_dt = datetime.now(tz=UTC)

        # Initialization codes
        for cmd in INIT_CMD:
            _ = self._wr(cmd)

    def _wr(self, data, readlen=40):
        """Write and read"""
        assert self._connected
        assert len(data) == 35
        tmpdt = datetime.now(tz=UTC)

        # Duration from the connection establishment
        ds_td = tmpdt - self._start_dt
        ds_int = int((ds_td.total_seconds() * 1e3) % 65536)
        ds_b = ds_int.to_bytes(2, 'little')

        # Packet index modulo 256
        pi_b = (self._packet_index % 256).to_bytes(1, 'little')

        # Packet creation
        pkt_pre = b'\xff' + data + ds_b + pi_b

        # The last byte is a parity
        parity = calc_parity(pkt_pre)
        pkt = pkt_pre + int(parity).to_bytes(1, 'little')

        self.__w(pkt)
        self._packet_index += 1

        return self.__r(readlen)

    def set_op_number(self, num):
        """Set operation number

        Parameter
        ---------
        num : int
            Operation number
        """
        assert 0 <= num < 16
        mark_0 = (((0b110 << 4) + num) << 5).to_bytes(2, 'little')
        mark_1 = (((num + 4) % 8) << 5) + (5 - int(num / 8))
        data = bytearray([0x03, 0x00, 0x01, 0x0a, 0x00, 0x86, 0x01]) + mark_0
        data += bytearray([0x04, 0x00, 0x00, mark_1]) + bytearray([0] * 22)

        return self._wr(data)

    def set_speed(self, speed):
        """Set speed

        Parameter
        ---------
        speed : int
            Speed in RPM
        """
        assert 50 <= speed <= 3000

        data = bytearray([0x03, 0x00, 0x01, 0x0c, 0x00, 0x81, 0x00, 0xc4, 0x01])
        data += speed.to_bytes(2, 'little')
        data += bytearray([0] * 3)

        # parity byte inside the packet.
        p_check = calc_parity(data[3:])
        data += bytearray([p_check] + [0] * 20)

        return self._wr(data)

    def set_accl_time(self, sec, accl=True):
        """Set acceleration time

        Parameters
        ----------
        sec : float
            Acceleration time in seconds

        accl : bool, default True
            True: Acceleration setting
            False: Decceleration setting
        """
        assert 0.5 <= sec <= 15.0

        data = bytearray([0x03, 0x00, 0x01, 0x0c, 0x00, 0x81, 0x00, 0xc5 if accl else 0xc6, 0x01])
        data += int(sec * 10).to_bytes(1, 'little')
        data += bytearray([0] * 4)

        # parity byte inside the packet
        p_check = calc_parity(data[3:])
        data += bytearray([p_check] + [0] * 20)
        return self._wr(data)

    def get_status(self):
        """Get status.

        Returns
        -------
        speed : int
            Speed in RPM
        """

        pkt_st = self._wr(STATUS, readlen=80)
        speed = int.from_bytes(pkt_st[7:11], 'little', signed=True)
        error = pkt_st[47]

        return speed, error

    def start(self, forward=True):
        """Start rotation.

        Parameter
        ---------
        forward : bool, default True
            Move forward if True

        Returns
        -------
        result : bool
            True if rotation command published correctly.
        """
        resp = self._wr(MOVE_FWD if forward else MOVE_BKW)
        result = resp[7] == 0

        return result

    def stop(self):
        """Stop rotation

        Returns
        -------
        result : bool
            True if stop command published correctly.
        """
        resp = self._wr(STOP)
        result = resp[7] == 0

        return result

    def clear_alarm(self):
        """Clear alarm"""
        self._wr(ALMCLR)


def main():
    """Test function"""
    blh = BLH()
    blh.connect()

    speed, error = blh.get_status()
    print(f'current speed: {speed}')
    print(f'current error: {error}')

    blh.set_speed(1500)
    blh.set_accl_time(5, False)
    blh.set_accl_time(5, True)

    print('MOVING FORWARD')
    blh.start(forward=True)
    for _ in range(200):
        print(f'{blh.get_status()}')
        sleep(0.1)

    print('STOPPED')
    blh.stop()
    for _ in range(10):
        print(f'{blh.get_status()}')
        sleep(0.1)

    print('MOVING BACKWARD')
    blh.start(forward=False)
    for _ in range(200):
        print(f'{blh.get_status()}')
        sleep(0.1)

    print('STOPPED')
    blh.stop()
    for _ in range(10):
        print(f'{blh.get_status()}')
        sleep(0.1)


if __name__ == '__main__':
    main()
