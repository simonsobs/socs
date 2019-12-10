#script to log and readout pfeiffer TPG 366 gauge contoller
#via Ethernet connection
#Zhilei X., Tanay B.

import socket
import numpy as np

BUFF_SIZE = 128
ENQ = '\x05'


class pfeiffer:
    def __init__(self, ip_address, port=8000, timeout=10):
        self.ip_address = ip_address
        self.port = port
        
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
    
    def read_pressure(self, ch_no):
        #measure the pressure of one given channel
        #ch_no is the chanel to be measured (e.g. 1-6)
        #returns the measured pressure as a float
        msg = 'PR%d\r\n'%ch_no
        self.comm.send(msg.encode())
        status = self.comm.recv(BUFF_SIZE).decode()#Could probably use this to catch exemptions
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        pressure_str = read_str.split(',')[-1].split('\r')[0]
        pressure = float(pressure_str)
        return pressure        

    def read_pressure_all(self):
        #measure the pressure of all channel
        #Return an array of 6 pressure values as a float array
        msg = 'PRX\r\n'
        self.comm.send(msg.encode())
        status = self.comm.recv(BUFF_SIZE).decode()#Could probably use this to catch exemptions
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        pressure_str = read_str.split('\r')[0]
        gauge_states = pressure_str.split(',')[::2]
        gauge_states = np.array(gauge_states, dtype=int)#this is recorded just incase
        pressures = pressure_str.split(',')[1::2]
        pressures = np.array(pressures, dtype=float)
        return pressures 

    def close(self):
        self.comm.close()
