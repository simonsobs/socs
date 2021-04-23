"""
Detect and record UDP stream(s) traffic.
"""

import socket
import struct
import json
import time

UDP_IP = "172.16.5.10"  # local host
#UDP_IP = "172.16.5.95"  # ACU
#UDP_IP = ''
#UDP_IP = "localhost"
UDP_PORTS = (10000,10001)

def get_sock(port, timeout=.3):
    sock = socket.socket(socket.AF_INET,
                         socket.SOCK_DGRAM)
    sock.bind((UDP_IP, port))
    sock.settimeout(timeout)
    return sock

format = '<iddd'

socks = [None for p in UDP_PORTS]

last_t = None
while True:
    for i, sock in enumerate(socks):
        if isinstance(sock, float):
            if time.time() < sock:
                continue
            sock = None
        if sock is None:
            sock = get_sock(UDP_PORTS[i], timeout=0.1)
        try:
            data, addr = sock.recvfrom(64000)
            socks[i] = sock
        except socket.timeout:
            print(f'(timeout {i})')
            socks[i] = time.time() + 1
            continue
        d = struct.unpack(format, data[:28])
        try:
            dt = d[1] - last_t
        except:
            dt = 0
        print(f'{i}  {d[0]} {d[1]} {dt}')
        last_t = d[1]
