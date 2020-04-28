import argparse
import time
import struct
import os
from pymodbus.client.sync import ModbusTcpClient
import numexpr
import json 

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


# Convert Data
def float2int(num):
    return struct.unpack("=i", struct.pack("=f", num))[0]


def concatData(data):
    tVal = 0
    upper = True
    for reg in data:
        if upper:
            tVal = ((reg & 0xFFFF) << 16)
            upper = False
        else:
            tVal = tVal | (reg & 0xFFFF)
            upper = True
    return tVal


# Converting numbers to 16-bit data arrays
def uint16_to_data(num):
    return struct.unpack("=H", struct.pack("=H", num & 0xFFFF))[0]


def uint32_to_data(num):
    data = [0, 0]
    data[0] = struct.unpack("=H", struct.pack("=H", (num >> 16) & 0xffff))[0]
    data[1] = struct.unpack("=H", struct.pack("=H", num & 0xffff))[0]
    return data


def int32_to_data(num):
    data = [0, 0]
    data[0] = struct.unpack("=H", struct.pack("=H", (num >> 16) & 0xffff))[0]
    data[1] = struct.unpack("=H", struct.pack("=H", num & 0xffff))[0]
    return data


def float32_to_data(num):
    intNum = float2int(num)
    data = [0, 0]
    data[0] = (intNum >> 16) & 0xFFFF
    data[1] = intNum & 0xFFFF
    return data


# Converting data arrays to numbers
def data_to_uint16(data):
    return data[0]


def data_to_uint32(data):
    return concatData(data)


def data_to_int32(data):
    return struct.unpack("=i", struct.pack("=I", concatData(data)))[0]


def data_to_float32(data):
    return struct.unpack("=f", struct.pack("=I", concatData(data)))[0]


# LabJack agent class
class LabJackAgent:
    def __init__(self, agent, ip_address, num_channels, functions={}):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.module = None
        self.sensors = ['Channel {}'.format(i+1) for i in range(num_channels)]
        self.functions = functions

        self.initialized = False
        self.take_data = False

        # Register feed
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('Sensors',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    # Task functions
    def init_labjack_task(self, session, params=None):
        """
        task to initialize labjack module
        """
        
        if self.initialized:
            return True, "Already initialized module"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')

            self.module = ModbusTcpClient(str(self.ip_address))

        print("Initialized labjack module")

        session.add_message("Labjack initialized")

        self.initialized = True
        
        # Start data acquisition if requested in site-config
        auto_acquire = params.get('auto_acquire', False)
        if auto_acquire:
            self.agent.start('acq')

        return True, 'LabJack module initialized.'

    def start_acq(self, session, params=None):
        """
        Task to start data acquisition.

        Args:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz

        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', 2.5)
        sleep_time = 1/f_sample - 0.01            
        
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'sens',
                    'data': {}
                }

                for i, sens in enumerate(self.sensors):
                    rr = self.module.read_input_registers(2*i, 2)
                    data['data'][sens + 'V'] = data_to_float32(rr.registers)
                    
                    #Apply conversion function if it exists
                    if sens in self.functions.keys():
                        v = data['data'][sens + 'V']
                        conversion = self.functions[sens][0]
                        units = self.functions[sens][1]
                        data['data'][sens + ' ' + units] = \
                        float(numexpr.evaluate(conversion))   

                time.sleep(sleep_time)

                self.agent.publish_to_feed('Sensors', data)
                
                # Allow this process to be queried to return current data
                print("Added session data")
                session.data = data

            self.agent.feeds['Sensors'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')

    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--num-channels', default='13')

    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'LabJackAgent')
    
    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}    

    ip_address = str(args.ip_address)
    num_channels = int(args.num_channels)
    functions = json.loads(args.functions)

    agent, runner = ocs_agent.init_site_agent(args)

    sensors = LabJackAgent(agent,
                           ip_address=ip_address,
                           num_channels=num_channels,
                          functions=functions)

    agent.register_task('init_labjack', 
                        sensors.init_labjack_task, 
                        startup=init_params)
    agent.register_process('acq', sensors.start_acq, sensors.stop_acq)

    runner.run(agent, auto_reconnect=True)
