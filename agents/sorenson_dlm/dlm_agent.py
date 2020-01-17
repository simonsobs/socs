#script to log and control the Sorenson DLM power supply, for heaters

import sys, os
import binascii
import time
import struct
import socket
import signal
import errno
from contextlib import contextmanager
from ocs import site_config, ocs_agent
from ocs.ocs_twisted import TimeoutLock

class DLM:
    def __init__(self, ip_address, port=502, timeout=10):
        self.ip_address = ip_address
        self.port = port
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
    def get_data(self):
        """
        Gets the raw data from the ptc and returns it in a usable format. 
        """
        self.comm.sendall(self.buildRegistersQuery()) 
        data = self.comm.recv(1024)
        brd = self.breakdownReplyData(data)
            
        return brd    
