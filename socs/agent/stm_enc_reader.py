#!/usr/bin/env python3
'''Module to run elevation encoder reader
'''
import socket
import selectors
import sys
import datetime

from datetime import timezone
from pathlib import Path
from os import getpid
from time import sleep

from socs.agent.common import is_writable

SERVER_IP = '192.168.10.13'
SERVER_PORT = 7
RECV_BUFLEN = 128*15
FILE_LEN = 1000000 # numbrer of packets per file
DIR_BASE = Path('.')
LOCK_PATH = Path('./el_enc.lock')
FNAME_FORMAT = 'el_%Y-%m%d-%H%M%S+0000.dat'
VERSION = 2021080501

HEADER_TXT = b'''Stimulator encoder data
Packet format: [HEADER 1][TS_LSB 4][TS_MSB 4][DATA 5][FOOTER 1]
\tIRIG: HEADER=0x55 FOOTER=0xAA
\t\tDATA=[SEC][MIN][HOUR][DAY 2]
\tENC : HEADER=0x99 FOOTER=0x66
\t\tDATA=[STATE 4][0x00]
'''


def path_checker(path):
    '''Path health checker
    '''
    if not path.exists():
        raise RuntimeError(f'Path {path} does not exist.')

    if not path.is_dir():
        raise RuntimeError(f'Path {path} is not a directory.')

    if not is_writable(path):
        raise RuntimeError(f'You do not have a write access to the path {path}')

def path_creator(dirpath, fmt=FNAME_FORMAT):
    '''Create path
    Parameters
    ----------
    dirpath: pathlib.Path
        Path to the base directory
    fmt: str
        Format of the filename

    Returns
    -------
    path: pathlib.Path
        Path to a new file
    '''
    utcnow = datetime.datetime.now(tz=timezone.utc)
    _d = dirpath.joinpath(f'{utcnow.year:04d}')
    _d = _d.joinpath(f'{utcnow.month:02d}')
    _d = _d.joinpath(f'{utcnow.day:02d}')
    _d.mkdir(exist_ok=True, parents=True)
    path = _d.joinpath(utcnow.strftime(fmt))
    if path.exists():
        raise RuntimeError(f'Filename collision: {path}.')
    return path


class StmEncReader:
    '''Class to read elevation data'''
    def __init__(self, ip_addr=SERVER_IP, port=SERVER_PORT, verbose=False,
                 lockpath=LOCK_PATH, path_base=DIR_BASE, file_len=FILE_LEN):
        self._verbose = verbose
        self._connected = False

        # Avoiding multiple launch
        self._lockpath = lockpath
        self._locked = False

        if lockpath.exists():
            raise RuntimeError(f'Locked: {lockpath}')

        if not is_writable(lockpath.parent):
            raise RuntimeError(f'No write access to {lockpath.parent}')

        with open(lockpath, 'w') as _f:
            _f.write(f'{getpid()}\n')

        self._locked = True

        # Connection data
        self._ip_addr = ip_addr
        self._port = port
        self._client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        # For filler
        self._sel = selectors.DefaultSelector()
        self._file_desc = None
        self._path_base = path_base
        self._file_len = file_len
        self._res = self._file_len*15
        self._carry_over = b''
        self.ts_latest = 0
        self.state_latest = 0


    def __del__(self):
        self._eprint('Deleted.')
        self._close()
        if self._locked:
            self._lockpath.unlink()
        self._eprint('Fin.')

    def _eprint(self, errmsg):
        if self._verbose:
            sys.stderr.write(f'{errmsg}\r\n')

    def _connect(self):
        if self._connected:
            self._eprint('Already connected.')
        else:
            self._client.connect((self._ip_addr, self._port))
            self._client.setblocking(False)
            self._sel.register(self._client, selectors.EVENT_READ)
            self._connected = True

    def connect(self):
        '''Establish connection to Zybo'''
        self._connect()

    def _close(self):
        if self._connected:
            self._client.close()
        else:
            self._eprint('Already closed.')

    def close(self):
        '''Close connection to Zybo'''
        self._close()
        self._current_path = None

    def _tcp_write(self, data):
        if self._connected:
            self._client.sendall(data)
        else:
            self._eprint('Not connected.')

    def _write_header(self):
        current_time = datetime.datetime.now()

        # HEADER
        header = b''
        header += b'256\n' # 4 bytes, 256 is the length of the header

        # 4 bytes, version number of the logger software
        header += VERSION.to_bytes(4, 'little', signed=False)
        utime = current_time.timestamp()
        utime_int = int(utime)

        # 4 bytes, integer part of the current time in unix time
        header += utime_int.to_bytes(4, 'little', signed=False)
        # microseconds
        header += int((utime - utime_int)*1e6).to_bytes(4, 'little', signed=False)
        header += HEADER_TXT
        res = 256 - len(header)
        if res < 0:
            raise Exception('HEADER TOO LONG')
        header += b' '*res # adjust header size with white spaces

        self._file_desc.write(header)


    def fill(self):
        '''Fill current file
        '''
        # initialization
        if self._file_desc is None:
            path = path_creator(self._path_base)
            self._file_desc = open(path, 'wb')
            self._write_header()
            self._res = self._file_len*15

        # body
        data = b''
        while self._sel.select(timeout=0) and self._res > 0:
            recv_num = RECV_BUFLEN if (self._res > RECV_BUFLEN) else self._res
            data_buf = self._client.recv(recv_num)
            data += data_buf
            self._res -= len(data_buf) 

        if not data:
            return

        self._file_desc.write(data)

        
        if self._res <= 0:
            self._file_desc.close()
            self._file_desc = None 

        # analyzer
        tmpd = self._carry_over + data
        pnum = len(tmpd)//15
        self._carry_over = tmpd[pnum*15:]


        for i in range(pnum):
            packet = tmpd[15*i:15*(i+1)]
            header = packet[0]
            ts_lsb = int.from_bytes(packet[1:5], 'little')
            ts_msb = int.from_bytes(packet[5:9], 'little')
            timestamp = ts_lsb + (ts_msb << 32)
            status = int.from_bytes(packet[9:13], 'little')
            footer = packet[14]
            if (header == 0x99) and (footer == 0x66):
                self.ts_latest = timestamp
                self.state_latest = status



def main():
    '''Main function to boot infinite loop'''
    elread = StmEncReader(verbose=True)

    # Filler loop
    try:
        elread.connect()
        while True:
            elread.fill()
            sleep(0.1)
    except KeyboardInterrupt:
        print('fin.')

if __name__ == '__main__':
    main()
