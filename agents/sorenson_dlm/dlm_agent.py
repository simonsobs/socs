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
    def __init__(self, ip_address = '10.10.10.21', port = 9221, timeout = 10):
        self.ip_address = ip_address
        self.port = port
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
        self.volt_prot = None
    
    def get_data(self):
        """
        Gets the raw data from the ptc and returns it in a usable format. 
        """
        self.comm.sendall(self.buildRegistersQuery()) 
        data = self.comm.recv(1024)
        brd = self.breakdownReplyData(data)
            
        return brd    
    
    def send_msg(self, cmd):
        """
        Sends a message to the DLM. OPC? causes the DLM to wait for the previous command to complete to being the next
        """
        msg = str(cmd) + ';OPC?\r\n'
        self.comm.send(msg.encode('ASCII'))

    def rec_msg(self):
        """
        Waits for a message from the DLM, typically as a result of a querry, and returns it
        """
        dataStr = self.comm.recv(1024).decode('ASCII')
        return dataStr.strip()

    def set_overv_prot(self, voltage):
        """
        Sets the overvoltage protection
        """
        send_msg(self, '*CLS')
        send_msg(self, '*RST')
        #TODO Figure out voltage formating: i.e. all voltage variables of the form 1.0? Also, check how DLM returns values and make sure check works
        send_msg(self, 'SOUR:VOLT:PROT {}'.format(voltage))
        
        send_msg(self, 'SOUR:VOLT:PROT?')
        ovp = rec_msg(self)
        if ovp != voltage:
            print("Error: Over voltage protection not set to requested value")
            return
        
        send_msg(self, 'STAT:PROT:ENABLE 8')
        send_msg(self, 'STAT:PROT:ENABLE?')
        enb = rec_msg(self)
        #TODO check that message returns string
        if enb != '8':
            print('Error: Over voltage protection failed to enable')
            return    

        send_msg(self, 'STAT:PROT:EVENT?')
        event = rec_msg(self)
        #TODO check that message returns string
        if event != '0':
            print('Error: Over voltage already tripped')
            return

class DLM_Agent:
    '''
    TO DO:
    start_acq function
    set_voltage function
    set_voltage_protection function
    ???
    '''


    def __init__(self,agent,ip_address = 10.10.10.21, porti=9221, f_sample=2.5):
        self.active = True
        self.agent= agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.f_sample = f_sample
        self.take_data = False
        agg_params = {'frame length':60, }
        self.agent.register_feed('pressures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
    def stop_act(self, session, params=None):
        '''
        End voltage data acquisition
        '''
        if self.take_data:
            self.take_data = False
            self.power_supply.close()
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'



if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip_address')
    pgroup.add_argument('--port')

    args = parser.parse_args()

    site_config.reparse_args(args, 'DLMAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    pfeiffer_agent = DLM_Agent(agent, args.ip_address, args.port)
    agent.register_process('acq', DLM_agent.start_acq,
                           DLMr_agent.stop_acq, startup=True)
    agent.register_task('close', DLM_agent.stop_acq)
    runner.run(agent, auto_reconnect=True)



#The following would be good for a client script
                  


def sendmsg(s, cmd):
    msg = str(cmd) + '; OPC?\r\n'
    s.send(msg.encode('ASCII'))

def recmsg(s):
    dataStr = s.recv(1024).decode('ASCII')    
    return dataStr.strip()    

comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
comm.connect(('10.10.10.21', 9221))
comm.settimeout(10)

sendmsg(comm, '*CLS')
sendmsg(comm, '*RST')
sendmsg(comm, 'SOUR:VOLT:PROT 100.0')    
sendmsg(comm, 'SOUR:CURR 1.0')
sendmsg(comm, 'SOUR:VOLT 2.0')
#sendmsg(comm, 'DISP:VIEW METER1')
#sendmsg(comm, 'SOUR:CURR?')
sendmsg(comm, 'SOUR:VOLT?')

msg = recmsg(comm)
print(msg)

sendmsg(comm, 'SOUR:CURR 0.0')
sendmsg(comm, 'SOUR:VOLT 0.0')
sendmsg(comm, 'SOUR:VOLT?')

msg = recmsg(comm)
print(msg)


comm.close()
"""
msg = '*CLS\n'
#comm.send(msg.encode())
comm.sendall(msg.encode('ASCII'))
msg = 'SYST:ERR?\n'
#comm.send(msg.encode())
comm.sendall(msg.encode('ASCII'))
status = comm.recv(4096).decode('ASCII')

print(status)
"""
