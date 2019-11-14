#script to log and readout PTC data through ethernet connection
#Tamar Ervin, September 2019

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

STX = '\x02'
ADDR = '\x10'
CMD = '\x80'
CR = '\x0D'
DATA_WRITE = '\x61'
DATA_READ = '\x63'
ESC = '\x07'
ESC_STX = '\x30'
ESC_CR = '\x31'
ESC_ESC = '\x32'

class TimeoutException(Exception): pass

@contextmanager
def time_limit(seconds):
    def signal_handler(signum, frame):
        raise TimeoutException ("Timed out!")
    signal.signal(signal.SIGALRM, signal_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)

class PTC:
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
    
    def buildRegistersQuery(self):
        query = bytes([0x09, 0x99,  # Message ID
                       0x00, 0x00,  # Unused
                       0x00, 0x06,  # Message size in bytes
                       0x01,        # Slave Address
                       0x04,        # Function Code  3= Read HOLDING registers, 4 read INPUT registers
                       0x00,0x01,   # The starting Register Number
                       0x00,0x35])  # How many to read
        return query

    def breakdownReplyData(self, rawdata):
        """
        Take in raw ptc data, and return a dictionary. The dictionary keys are the data labels, 
        the dictionary values are the data in floats or ints. 
        """
        
        #Associations between keys and their location in rawData
        keyloc = {"Operating State": [9,10], "Pump State": [11, 12], "Warnings": [15, 16, 13, 14], "Alarms":[19, 20, 17, 18],
                  "Coolant In": [22, 21, 24, 23], "Coolant Out": [26, 25, 28, 27], "Oil": [30, 29, 32, 31], 
                  "Helium": [34, 33, 36, 35], "Low Pressure": [38, 37, 40, 39], "Low Pressure Average":[42, 41, 44, 43],
                  "High Pressure": [46,45,48,47], "High Pressure Average": [50, 49, 52, 51], "Delta Pressure": [54, 53, 56, 55],
                  "Motor Current": [58, 57, 60, 59]}
        
        #Iterate through all keys and return the data in a usable format
        data = {}
        for key in keyloc.keys():
            locs = keyloc[key] 
            wkrBytes = bytes([rawdata[loc] for loc in locs])
            
            #three different data formats to unpack
            if key in ["Operating State", "Pump State"]:
                state = int.from_bytes(wkrBytes, byteorder='big')
                data[key] = state
            
            if key in ["Warnings", "Alarms"]:
                data[key] = int(''.join('{:02x}'.format(x) for x in wkrBytes))
                
            if key in ["Coolant In", "Coolant Out", "Oil", "Helium", "Low Pressure", "Low Pressure Average","High Pressure", "High Pressure Average", "Delta Pressure","Motor Current"]:
                data[key] = struct.unpack('f', wkrBytes)[0]
                
        return data
    
    def __del__(self):
        """
        If the PTC class instance is destroyed, close the connection to the ptc. 
        """
        self.comm.close()

class PTCAgent:
    def __init__(self, agent, serial_mode, port, ip_address, f_sample=2.5):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address

        self.port = port
        self.module: Optional[Module] = None
        self.f_sample = f_sample
        
        self.initialized = False
        self.take_data = False

        # Registers data feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('ptc_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
        
    def init_ptc_task(self, session, params=None):
        """
        Initializes the connection to the ptc. 
        """
        if params is None:
            params = {}

        auto_acquire = params.get('auto_acquire', False)
        
        if self.initialized:
            return True, "Already Initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')
            #Establish connection to ptc
            self.ptc = PTC(self.ip_address, self.port)

        self.initialized = True

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, "PTC agent initialized"          


    def start_acq(self, session, params=None):
        """
        Starts acqusition of data from the ptc.
        """
        
        if params is None:
            params = {}

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True
            
            #Publish data, waiting 1/f_sample seconds in between calls. 
            while self.take_data:
                pub_data = {'timestamp':time.time(), 'block_name':'ptc_status'}
                data = self.ptc.get_data()
                pub_data['data'] = data
                time.sleep(1./self.f_sample)
                self.agent.publish_to_feed('ptc_status',pub_data)

            self.agent.feeds["ptc_status"].flush_buffer() 

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acqusition of data from the ptc..
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'        
        
        
def main():
    parser = site_config.add_arguments()
    
    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--mode')
    pgroup.add_argument('--port')
    
    # Get the parser to process the command line.
    args = parser.parse_args()

    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'CryomechCPA1114Agent')
    print('I am in charge of device with serial number: %s' % args.serial_number)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    #create agent instance and run log creation
    ptc = PTCAgent(agent, 'modbus', args.port, args.ip_address)  

    agent.register_task('init',  ptc.init_ptc_task, startup=init_params)
    agent.register_process('acq', ptc.start_acq, ptc.stop_acq)

    runner.run(agent, auto_reconnect=True)
                                 
if __name__ == '__main__':
    main()
        
