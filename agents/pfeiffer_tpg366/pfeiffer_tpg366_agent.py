#script to log and readout pfeiffer TPG 366 gauge contoller
#via Ethernet connection
#Zhilei X., Tanay B.

import socket
import numpy as np
from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock
import time

BUFF_SIZE = 128
ENQ = '\x05'
IP_ADDRESS = '10.10.10.20'

class pfeiffer:
    """CLASS to control and retrieve data from the pfeiffer tpg366 
    pressure gauage controller
    ip_address: ip address of the deivce
    port: 8000 (fixed for the device)
    Attributes:
       read_pressure reads the pressure from one channel (given as an argument)
       read_pressure_all reads pressrue from the six channels
       close closes the socket
    """
    def __init__(self, ip_address=IP_ADDRESS, port=8000, timeout=10):
        self.ip_address = ip_address
        self.port = port
        
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
    
    def read_pressure(self, ch_no):
        """Function to measure the pressure of one given channel
        ch_no is the chanel to be measured (e.g. 1-6)
        returns the measured pressure as a float
        """
        msg = 'PR%d\r\n'%ch_no
        self.comm.send(msg.encode())
        status = self.comm.recv(BUFF_SIZE).decode()#Could probably use this to catch exemptions
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        pressure_str = read_str.split(',')[-1].split('\r')[0]
        pressure = float(pressure_str)
        return pressure        

    def read_pressure_all(self):
        """measure the pressure of all channel
        Return an array of 6 pressure values as a float array
        """
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
        """Close the socket of the connection
        """
        self.comm.close()

class pfeifferAgent:
    def __init__(self, agent,ip_address = IP_ADDRESS, port=8000):
        self.active = True  
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False


        self.port = port
        self.ip_address = ip_address
       
        agg_params = {'frame length':60,}

        self.agent.register_feed('pressures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
    def get_pressure(self, params = None):
        """
        Get pressures from the Pfeiffer gauges
        """
        with self.acquire_timeout(timeout=0, job='init') as acquired:
        # Locking mechanism stops code from proceeding if no lock acquired
        if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
        # Run the function you want to run
        try:
                self.read_pressure_all.()
        except ValueError:
                pass
        print("Retreiving pressure data from Pfeiffer gauges")
        # This part is for the record and to allow future calls to proceed, so does not require the lock
        self.initialized = True
        return True, 'Retreiving pressure data'

    def stop_acq(self, params = None):
        """
        End pressure data acquisition
        """
        if self.take_data:
            #self.take_data = False
            self.close()
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

if __name__ == '__main__':
        parser = site_config.add_arguments()

        pgroup = parser.add_argument_group('Agent Options')
        pgroup.add_argument('--ip_address')
        pgroup.add_argument('--port')

        args = parser.parse_args()
        

        site_config.reparse_args(args, 'pfeifferAgent')
        agent, runner = ocs_agent.init_site_agent(args)
        pfeiffer_agent = pfeifferAgent(agent) 
        
        agent.register_task('get_pressure', pfeiffer_agent.get_pressure)
        agent.register_task('close', pfeiffer_agent.stop_acq)

        runner.run(agent, auto_reconnect=True)
