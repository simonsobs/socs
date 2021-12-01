#!/usr/bin/env python3
'''Module to handle MAX31856
   Descriptions can be found at https://datasheets.maximintegrated.com/en/ds/MAX31856.pdf
'''
from sys import stderr
from time import sleep
import sys
import spidev

MAX_SPEED = 1000000

CR0 = 0x00
CR0_CMODE    = 0b1000_0000
CR0_1SHOT    = 0b0100_0000
CR0_OCFAULT1 = 0b0010_0000
CR0_OCFAULT0 = 0b0001_0000
CR0_OCFAULT  = 0b0011_0000
CR0_CJ       = 0b0000_1000
CR0_FAULT    = 0b0000_0100
CR0_FAULTCLR = 0b0000_0010
CR0_50_60HZ  = 0b0000_0001

CR1 = 0x01
CR1_AVGSEL2  = 0b0100_0000
CR1_AVGSEL1  = 0b0010_0000
CR1_AVGSEL0  = 0b0001_0000
CR1_AVGSEL   = 0b0111_0000
CR1_TCTYPE3  = 0b0000_1000
CR1_TCTYPE2  = 0b0000_0100
CR1_TCTYPE1  = 0b0000_0010
CR1_TCTYPE0  = 0b0000_0001
CR1_TCTYPE   = 0b0000_1111

MASK = 0x02
MASK_CJHIGH  = 0b0010_0000
MASK_CJLOW   = 0b0001_0000
MASK_TCHIGH  = 0b0000_1000
MASK_TCLOW   = 0b0000_0100
MASK_OVUV    = 0b0000_0010
MASK_OPEN    = 0b0000_0001

CJHF   = 0x03
CJLF   = 0x04
LTHFTH = 0x05
LTHFTL = 0x06
LTLFTH = 0x07
LTLFTL = 0x08
CJTO   = 0x09
CJTH   = 0x0A
CJTL   = 0x0B
LTCBH  = 0x0C
LTCBM  = 0x0D
LTCBL  = 0x0E
SR     = 0x0F

class Max31856Error(Exception):
    '''Exception raised by MAX31856'''


class Max31856Config:
    '''Class to handle configuration of the MAX31856 chip

    Attributes
    ----------
    cmode : int
        Conversion mode.
        0: normally off, 1: automatic conversion
    ocfault : int
        see p.14
    cj_disabled : int
        Cold-junction sensor disable.
        0: enabled, 1: disabled
    fault : int
        Fault mode.
        0: comparator mode, 1: interrupt mode
    nrf50 : int
        50Hz/60Hz noise rejection filter.
        0: 60 Hz and harmonics
        1: 50 Hz and harmonics
    avgsel : int
        Averaging mode.
        0: 1 sample, 1: 2 samples, 2: 4 samples,
        3: 8 samples, 4+: 16 samples
    tc_type : int
        Themocouple type.
        0: B, 1: E, 2: J, 3: K, 4: N, 5: R, 6: S, 7: T
        8: Voltage mode, gain 8
        12: Voltage mode, gain 32
    '''
    def __init__(self, **kwargs):
        self.cmode = kwargs['cmode']
        self.ocfault = kwargs['ocfault']
        self.cj_disabled = kwargs['cj_disabled']
        self.fault = kwargs['fault']
        self.nrf50 = kwargs['nrf50']

        self.avgsel = kwargs['avgsel']
        self.tc_type = kwargs['tc_type']

    @property
    def cr0(self):
        '''0th configuration register

        Returns
        -------
        cr0_expr : int
            Expression of CR0
        '''
        cr0_expr = 0
        cr0_expr += CR0_CMODE*self.cmode
        cr0_expr += CR0_OCFAULT0*self.ocfault
        cr0_expr += CR0_CJ*self.cj_disabled
        cr0_expr += CR0_FAULT*self.fault
        cr0_expr += CR0_50_60HZ*self.nrf50

        return cr0_expr

    @property
    def cr1(self):
        '''1st configuration register

        Returns
        -------
        cr1_expr : int
            Expression of CR1
        '''
        cr1_expr = 0
        cr1_expr += CR1_AVGSEL0*self.avgsel
        cr1_expr += CR1_TCTYPE0*self.tc_type
        return cr1_expr

    @classmethod
    def parse(cls, cr0, cr1):
        '''Parser'''
        kwargs = {}
        kwargs['cmode'] = (cr0 & CR0_CMODE) >> 7
        kwargs['ocfault'] = (cr0 & CR0_OCFAULT) >> 4
        kwargs['cj_disabled'] = (cr0 & CR0_CJ) >> 3
        kwargs['fault'] = (cr0 & CR0_FAULT) >> 2
        kwargs['nrf50'] = (cr0 & CR0_50_60HZ) >> 0

        kwargs['avgsel'] = (cr1 & CR1_AVGSEL) >> 4
        kwargs['tc_type'] = (cr1 & CR1_TCTYPE)
        return cls(**kwargs)


class Max31856:
    '''Max31856 device class.
    '''
    def __init__(self, spibus=0, cs=0):
        '''
        Parameters
        ----------
        spibus : int, default 0
            SPI bus number
        cs : int, default 0
            Chip select number
        '''
        self._dev = spidev.SpiDev()
        try:
            self._dev.open(spibus, cs)
            self._dev.mode = 1
            self._dev.max_speed_hz = MAX_SPEED
            self._dev.bits_per_word = 8
        except PermissionError:
            print("You don't have permission.", file=stderr)
            sys.exit(1)

    def _r(self, address, num=1):
        ret = self._dev.xfer2([address] + [0]*num)
        if num == 1:
            return ret[1]

        return ret[1:]

    def _w(self, address, message):
        assert 0x00 <= address <= 0x0F
        if isinstance(message, int):
            assert 0x00 <= message <= 0xFF
            message = [message]
        elif isinstance(message, list):
            for _m in message:
                assert 0x00 <= _m <= 0xFF
        else:
            raise Max31856Error(f'Message invalid: {message}')

        self._dev.xfer2([address + 0x80] + message)

    @property
    def config(self):
        '''Read the configuration registers

        Returns
        -------
        conf : Max31856Config
            Configuration of the device
        '''
        cr0 = self._r(CR0)
        cr1 = self._r(CR1)
        conf = Max31856Config.parse(cr0, cr1)
        return conf

    @config.setter
    def config(self, config_new):
        '''Set the configuration registers

        Parameters
        ----------
        config_new : Max31856Config
            New configuration
        '''
        assert isinstance(config_new, Max31856Config)
        self._w(CR0, config_new.cr0)
        self._w(CR1, config_new.cr1)

    def oneshot(self):
        '''Fire one-shot conversion'''
        cr0 = self._r(CR0)
        self._w(CR0, cr0 | CR0_1SHOT)

    def get_temp(self, oneshot=True):
        '''Read thermocouple temperature.

        Parameters
        ----------
        oneshot : bool, default True
            perform/skip self.oneshot()
        '''
        if oneshot:
            self.oneshot()
            sleep(0.2)

        ret = self._r(LTCBH, 3)
        val = int.from_bytes(bytearray(ret),
                             byteorder='big',
                             signed=True)
        return val / (1 << (4 + 8))

    def get_cjtemp(self, oneshot=True):
        '''Read cold-junction temperature.

        Parameters
        ----------
        oneshot : bool, default True
            perform/skip self.oneshot()
        '''
        if oneshot:
            self.oneshot()
            sleep(0.2)

        ret = self._r(CJTH, 2)
        val = int.from_bytes(bytearray(ret),
                             byteorder='big',
                             signed=True)
        return val / (1 << 8)


def main():
    ''' Main function '''
    tc_reader = Max31856(0, int(sys.argv[1]))
    print(tc_reader.get_temp(), tc_reader.get_cjtemp(oneshot=False))

if __name__ == '__main__':
    main()
