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
        self.send_msg('*CLS')
        self.send_msg('*RST')
        #TODO Figure out voltage formating: i.e. all voltage variables of the form 1.0? Also, check how DLM returns values and make sure check works
        self.send_msg('SOUR:VOLT:PROT {}'.format(voltage))
        
        self.send_msg('SOUR:VOLT:PROT?')
        ovp = self.rec_msg()
        if ovp != voltage:
            print("Error: Over voltage protection not set to requested value")
            return
        
        self.send_msg('STAT:PROT:ENABLE 8')
        self.send_msg('STAT:PROT:ENABLE?')
        enb = self.rec_msg()
        #TODO check that message returns string
        if enb != '8':
            print('Error: Over voltage protection failed to enable')
            return    

        self.send_msg('STAT:PROT:EVENT?')
        event = self.rec_msg()
        #TODO check that message returns string
        if event != '0':
            print('Error: Over voltage already tripped')
            return

    def read_voltage(self):
        """
        Reads output  voltage
        """
        self.send_msg('SOUR:VOLT?')
        msg = self.rec_msg()
        print(msg)
        return msg

    def read_current(self):
        """
        Reads output current
        """
        self.send_msg('MEAS:CURR?')
        msg = self.rec_msg()
        return msg

    def sys_err_check(self):
        """
        Queries sytem error and returns error byte
        """
        self.send_msg('SYST:ERR?')
        msg = self.rec_msg()
        return msg


class DLMAgent:
    '''
    TO DO:
    start_acq function
    set_voltage function
    set_voltage_protection function
    set_current_fuction
    set_current_and_voltage??? (simulatneously set current and voltage, not sure if needed)
    
    ???
    '''


    def __init__(self,agent,ip_address , port, f_sample=2.5):
        self.active = True
        self.agent= agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.f_sample = f_sample
        self.take_data = False
        self.dlm = DLM(ip_address, int(port))
        agg_params = {'frame length':60, }
        self.agent.register_feed('voltages',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params=None):
        
        if params is None:
            params = {}
        
        f_sample = params.get('sampling_frequency')
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1./f_sample - 0.01
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'voltages',
                    'data': {}
                }
                voltage_reading = self.dlm.read_voltage()
                # Loop through all the channels on the device
                data['data']["voltage"] = voltage_reading

                self.agent.publish_to_feed('voltages', data)
                time.sleep(sleep_time)

            self.agents.feeds['voltages'].flush_buffer()
        return True, 'Acquistion exited cleanly'

    def set_voltage(self, voltage = '1.0'):
        """
        Sets voltage of power supply:
        Args:
            volts (float): Voltage to set. Must be between 0 and 30.
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.dlm.send_msg('SOUR:VOLT {}'.format(voltage))
            else:
                return False, "Could not acquire lock"

        return True, 'Set voltage to {}'.format(voltage)


    def stop_acq(self, session, params=None):
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
    DLM_agent = DLMAgent(agent, args.ip_address, args.port)
    agent.register_process('acq', DLM_agent.start_acq,
                           DLM_agent.stop_acq, startup=True)   
    agent.register_task('set_voltage', DLM_agent.set_voltage)
    agent.register_task('close', DLM_agent.stop_acq)
    runner.run(agent, auto_reconnect=True)



#The following would be good for a client script
                  

"""
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
print("msg",msg)

sendmsg(comm, 'SOUR:CURR 0.0')
sendmsg(comm, 'SOUR:VOLT 0.0')
sendmsg(comm, 'SOUR:VOLT?')

msg = recmsg(comm)
print(msg)


comm.close()

msg = '*CLS\n'
#comm.send(msg.encode())
comm.sendall(msg.encode('ASCII'))
msg = 'SYST:ERR?\n'
#comm.send(msg.encode())
comm.sendall(msg.encode('ASCII'))
status = comm.recv(4096).decode('ASCII')

print(status)
"""
