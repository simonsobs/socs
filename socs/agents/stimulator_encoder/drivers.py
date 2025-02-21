#!/usr/bin/env python3
"""Module to read stimulator encoder.
"""
import fcntl
import mmap
import os
import sys
from pathlib import Path
from queue import Queue
from threading import Thread
from time import sleep, time

import numpy as np

ADDR_AXI = 0x80020000
PATH_DEV_BASE = Path(f'/sys/devices/platform/axi/{ADDR_AXI:08x}.str_rd/uio')
PATH_LOCK = Path('/tmp/').joinpath('.stim-lock')


class StimEncError(Exception):
    """
    Exception rased by stimulator encoder reader.
    """


class StimEncTime:
    """
    Stimulator encoder time.

    Parameter
    ---------
    time_raw : int
        Raw time format from TSU.
        [sec 48 bits][nsec 30 bits][sub-nsec 16 bits]
    """

    def __init__(self, time_raw: int):
        self._time_raw = time_raw

    @property
    def sec(self) -> int:
        """
        Seconds part of timestamp.

        Returns
        -------
        sec : int
            Seconds part of timestamp.
        """
        return self._time_raw >> 46

    @property
    def nsec(self) -> int:
        """
        Nano second part of timestamp.

        Returns
        -------
        nsec : int
            Nano-sec part of timestamp.
        """
        return (0x_00000000_00003fff_ffff0000 & self._time_raw) >> 16

    @property
    def tai(self) -> float:
        """
        Time in seconds from TAI epoch.

        Returns
        -------
        tai : float
            Seconds from TAI epoch.
        """
        return self.sec + (self.nsec / 1e9)


class StimEncData:
    """
    Stimulator encoder data.

    Parameter
    ---------
    data_raw : ndarray
        Raw data from PL FIFO.
    """

    def __init__(self, data_bytes):
        self._data_bytes = data_bytes
        self._data_int = int(data_bytes[0]) + (int(data_bytes[1]) << 32) + (int(data_bytes[2]) << 64)
        self._utime = time()

    @property
    def state(self) -> int:
        return (self._data_int & 0xC0_00_00_00_00000000_00000000) >> 94

    @property
    def time_raw(self) -> int:
        """94 bit TSU timestamp.

        Returns
        -------
        time_raw : int
            94 bit TSU timestamp.
        """
        return self._data_int & 0x3F_FF_FF_FF_FFFFFFFF_FFFFFFFF

    @property
    def time(self) -> StimEncTime:
        """
        TSU timestamp.

        Returns
        -------
        time : StimTime
            TSU timestamp abstraction.
        """
        return StimEncTime(self.time_raw)

    @property
    def utime(self) -> float:
        """
        Unix timestamp at class creation.

        Returns
        -------
        utime : Unix timestamp when this object is created.
        """
        return self._utime

    def __str__(self):
        return f'time={int(self.time.g3) / 1e8:.8f} data={self.state:02b}'


def get_path_dev() -> Path:
    """
    Acquire devicefile path for `str_rd` IP core.

    Returns
    -------
    path_dev : Path
        Path to the device file.
    """
    if not PATH_DEV_BASE.exists():
        raise StimEncError('Device is not found. Check firmware and device tree.')

    name_dev = list(PATH_DEV_BASE.glob('uio*'))[0].name
    path_dev = Path(f'/dev/{name_dev}')

    return path_dev


class StimEncReader:
    """Class to read encoder data.

    Parameters
    ----------
    path_dev : str or pathlib.Path
        Path to the generic-uio device file for str_rd IP.
    path_lock : str or pathlib.Path
        Path to the lockfile.
    """

    def __init__(self, path_dev, path_lock=PATH_LOCK, verbose=True):
        # Verbose level
        self._verbose = verbose

        # Locking
        self._fp_lock = open(path_lock, 'w')
        try:
            fcntl.flock(self._fp_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except IOError:
            raise StimEncError('locked.')

        # Connection
        self._path_dev = path_dev
        self._dfile = os.open(self._path_dev, os.O_RDONLY | os.O_SYNC)
        self._dev = mmap.mmap(self._dfile, 0x100, mmap.MAP_SHARED, mmap.PROT_READ, offset=0)

        # Data FIFO
        self.fifo: "Queue[StimEncData]" = Queue()

        # Runner
        self._thread = None
        self._running = False

    def __del__(self):
        if self._running:
            self.stop()
        fcntl.flock(self._fp_lock, fcntl.LOCK_UN)
        self._dev.close()
        os.close(self._dfile)

        self._eprint('Fin.')

    def _eprint(self, errmsg):
        if self._verbose:
            sys.stderr.write(f'{errmsg}\r\n')

    def _get_info(self):
        data = np.frombuffer(self._dev, np.uint32, 4, offset=0)
        r_len = data[0]
        w_len = data[1]
        residue = data[2]

        return r_len, w_len, residue

    def _get_data(self) -> StimEncData:
        data = np.frombuffer(self._dev, np.uint32, 4, offset=16)

        return StimEncData(data)

    def fill(self):
        """
        Get data from PL fifo and put into software fifo.
        """
        while True:
            r_len, w_len, residue = self._get_info()

            if (r_len == 0) and (residue == 0):
                break

            self.fifo.put(self._get_data())

    def _loop(self):
        while self._running:
            self.fill()
            sleep(0.1)

    def run(self):
        """
        Run infinite loop of data filling.
        """
        self._running = True
        self._thread = Thread(target=self._loop)
        self._thread.start()

    def stop(self):
        if not self._running:
            raise StimEncError('Not started yet.')

        self._running = False
        self._thread.join()


def main():
    """Main function to boot infinite loop"""
    stim_enc = StimEncReader(get_path_dev(), verbose=True)

    # Filler loop
    fd = open('test.dat', 'w')
    stim_enc.run()
    while True:
        try:
            while not stim_enc.fifo.empty():
                data = stim_enc.fifo.get()
                print(data)
                fd.write(str(data) + '\n')
            sleep(0.1)
        except KeyboardInterrupt:
            stim_enc.stop()
            fd.close()
            break

    print('Fin.')


if __name__ == '__main__':
    main()
