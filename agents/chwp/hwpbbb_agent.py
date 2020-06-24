import socket
import numpy
import struct
import time
from collections import deque
import select

## Required by OCS
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# The number of datapoints in every encoder packet from the Arduino/Beaglebone
COUNTER_INFO_LENGTH = 150
# The size of the encoder packet from the Arduino (header + 3*150 datapoint information + 1 quadrature readout)
COUNTER_PACKET_SIZE = 4 + 4 * COUNTER_INFO_LENGTH+8 * COUNTER_INFO_LENGTH + 4
# The size of the IRIG packet from the Arduino/Beaglebone
IRIG_PACKET_SIZE = 132
# The slit scaler value for rough HWP rotating frequency
NUM_SLITS = 570

### Definitions of utility functions ###

# Converts the IRIG signal into sec/min/hours depending on the parameters
def de_irig(val, base_shift=0):
    return (((val >> (0+base_shift)) & 1) 
            + ((val >> (1+base_shift)) & 1) * 2
            + ((val >> (2+base_shift)) & 1) * 4 
            + ((val >> (3+base_shift)) & 1) * 8 
            + ((val >> (5+base_shift)) & 1) * 10 
            + ((val >> (6+base_shift)) & 1) * 20 
            + ((val >> (7+base_shift)) & 1) * 40
            + ((val >> (8+base_shift)) & 1) * 80
    )
        
# Class which will parse the incoming packets from the BeagleboneBlack and store the data
class EncoderParser(object):
    # port: This must be the same as the localPort in the Arduino/Beaglebone code
    # read_chunk_size: This value shouldn't need to change
    
    def __init__(self, beaglebone_port=8080, read_chunk_size=8196):
        # Creates three queues to hold the data from the encoder, IRIG, and quadrature respectively
        self.counter_queue = deque()
        self.irig_queue = deque()
        self.quad_queue = deque()

        # Used for procedures that only run when data collection begins
        self.is_start = 1
        # Will hold the time at which data collection started [hours, mins, secs]
        self.start_time = [0,0,0]
        # Will be continually updated with the UTC time in seconds
        self.current_time = 0

        # Creates a UDP socket to connect to the Arduino/Beaglebone
        self.s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Binds the socket to a specific ip address and port
        # The ip address can be blank for accepting any UDP packet to the port
        self.s.bind(('', beaglebone_port))
        #self.s.setblocking(0)
        
        # String which will hold the raw data from the Arduino/Beaglebone before it is parsed
        self.data = ''
        self.read_chunk_size = read_chunk_size

        # Keeps track of how many packets have been parsed
        self.counter = 0

    # Takes the IRIG information, prints it to the screen, sets the current time,
    # and returns the current time
    def pretty_print_irig_info(self, v, edge):
        # Calls self.de_irig() to get the sec/min/hour of the IRIG packet
        secs =  de_irig(v[0], 1)
        mins =  de_irig(v[1], 0)
        hours = de_irig(v[2], 0)

        # If it is the first time that the function is called then set self.start_time
        # to the current time
        if self.is_start == 1:
            self.start_time = [hours, mins, secs]
            self.is_start = 0

        # Find the sec/min/hour digit difference from the start time
        dsecs = secs - self.start_time[2]
        dmins = mins - self.start_time[1]
        dhours = hours - self.start_time[0]

        # Corrections to make sure that dsecs/dmins/dhours are all positive
        if dhours < 0:
            dhours = dhours + 24

        if (dmins < 0) or ((dmins == 0) and (dsecs < 0)):
            dmins = dmins + 60
            dhours = dhours - 1

        if dsecs < 0:
            dsecs = dsecs + 60
            dmins = dmins - 1
        
        # Print UTC time, run time, and current clock count of the Arduino
        print('Current Time:',('%d:%d:%d'%(hours, mins, secs)), \
              'Run Time',('%d:%d:%d'%(dhours, dmins, dsecs)), \
              'Clock Count',edge)

        # Set the current time in seconds
        self.current_time = secs + mins*60 + hours*3600

        return self.current_time

    # Checks to make sure that self.data is the right size
    # Return false if the wrong size, return true if the data is the right size
    def check_data_length(self, start_index, size_of_read):
        if start_index + size_of_read > len(self.data):
            self.data = self.data[start_index:]
            print('Invalid data size')
            return False
        else:
            return True

    # Grabs self.data, determine what packet it corresponds to, parses the data
    def grab_and_parse_data(self):
        while True:
            # If there is data from the socket attached to the Arduino then ready[0] = true
            # If not then continue checking for 2 seconds and if there is still no data ready[0] = false
            ready = select.select([self.s],[],[],2)
            if ready[0]:
                # Add the data from the socket attached to the Arduino to the string self.data

                data = self.s.recv(self.read_chunk_size)
                if len(self.data)>0: self.data += data
                else:                self.data = data
                while True:
                    # Check to make sure that there is at least 1 int in the packet
                    # The first int in every packet should be the header
                    if not self.check_data_length(0, 4):
                        print('Error 0')
                        break

                    header = self.data[0:4]
                    # Convert a structure value from the Arduino (header) to an int
                    header = struct.unpack('<I', header)[0]
                    #print('header ', '0x%x'%header)

                    # 0x1EAF = Encoder Packet
                    # 0xCAFE = IRIG Packet
                    # 0xE12A = Error Packet

                    # Encoder
                    if header == 0x1eaf:
                        # Make sure the data is the correct length for an Encoder Packet
                        if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                            print('Error 1')
                            break
                        # Call the meathod self.parse_counter_info() to parse the Encoder Packet
                        self.parse_counter_info(self.data[4 : COUNTER_PACKET_SIZE])
                        # Increment self.counter to signify that an Encoder Packet has been parsed
                        self.counter += 1

                    # IRIG
                    elif header == 0xcafe:
                        # Make sure the data is the correct length for an IRIG Packet
                        if not self.check_data_length(0, IRIG_PACKET_SIZE):
                            print('Error 2')
                            break
                        # Call the meathod self.parse_irig_info() to parse the IRIG Packet
                        self.parse_irig_info(self.data[4 : IRIG_PACKET_SIZE])

                    # Error
                    # An Error Packet will be sent if there is a timing error in the 
                    # synchronization pulses of the IRIG packet
                    # If you see 'Packet Error' check to make sure the IRIG is functioning as
                    # intended and that all the connections are made correctly 
                    elif header == 0xe12a:
                        print('Packet Error')
                    else:
                        print('Bad header')

                    # Clear self.data
                    self.data = ''
                    break
                break
            
            # If there is no data from the Arduino/beaglebone 'Looking for data ...' will print
            # If you see this make sure that the Arduino has been set up properly
            else:
                print('Looking for data ...')

    # Meathod to parse the Encoder Packet
    def parse_counter_info(self, data):
        # Convert the Encoder Packet structure into a numpy array
        derter = numpy.array(struct.unpack('<' + 'I'+ 'III'*COUNTER_INFO_LENGTH, data))

        # [1-150] clock counts of 150 data points
        # [151-300] corresponding clock overflow of the 150 data points (each overflow count
        # is equal to 2^16 clock counts)
        # [301-450] corresponding absolute number of the 150 data points ((1, 2, 3, etc ...)
        # or (150, 151, 152, etc ...) or (301, 302, 303, etc ...) etc ...)
        # [0] Readout from the quadrature

        self.quad_queue.append(derter[0].item())

        # self.counter_queue = [[clock count array],[absolute number array], quad]
        self.counter_queue.append(( derter[1:151] + (derter[151:301] << 32), derter[301:451]))

    # Meathod to parse the IRIG Packet
    def parse_irig_info(self, data):
        # Convert the IRIG Packet structure into a numpy array
        unpacked_data = struct.unpack('<L' + 'L' + 'L'*10 + 'L'*10 + 'L'*10, data)

        # [0] clock count of the IRIG Packet which the UTC time corresponds to
	# [1] overflow count of initial rising edge
        # [2] binary encoding of the second data
        # [3] binary encoding of the minute data
        # [4] binary encoding of the hour data
        # [5-11] additional IRIG information which we do mot use
        # [12-21] synchronization pulse clock counts
	# [22-31] overflow count at each synchronization pulse

        # Start of the packet clock count
	#overflow.append(unpacked_data[1])
        #print "overflow: ", overflow
        rising_edge_time = unpacked_data[0] + (unpacked_data[1] << 32)
        # Stores IRIG time data
        irig_info = unpacked_data[2:12]

        # Prints the time information and returns the current time in seconds
        irig_time = self.pretty_print_irig_info(irig_info, rising_edge_time)
        # Stores synch pulse clock counts accounting for overflow of 32 bit counter
        synch_pulse_clock_times = (numpy.asarray(unpacked_data[12:22]) + (numpy.asarray(unpacked_data[22:]) << 32)).tolist()

        # self.irig_queue = [Packet clock count,Packet UTC time in sec,[binary encoded IRIG data],[synch pulses clock counts]]
        self.irig_queue.append((rising_edge_time, irig_time, irig_info, synch_pulse_clock_times))

    def __del__(self):
        self.s.close()

# OCS agent for HWP encoder DAQ using Beaglebone Black
class HWPBBBAgent:

    def __init__(self, agent, port=8080):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.port = port
        self.take_data = False
        self.initialized = False

        ## Defining feed for IRIG, quadrature and counter dta because of they have different sampling rates.
        agg_params = {'frame_length': 60}
        self.agent.register_feed('HWPEncoder_irig',    record=True, agg_params=agg_params,buffer_time=1)
        self.agent.register_feed('HWPEncoder_quad',    record=True, agg_params=agg_params,buffer_time=1)
        ## counter data are relatively high-sampling-rate data
        agg_params_counter = {'frame_length': 1}
        self.agent.register_feed('HWPEncoder_counter', record=True, agg_params=agg_params_counter)

        self.ep = EncoderParser()

    def start_acq(self, session, params):
        """Starts acquiring data.
        """

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn('Could not start acq because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock.'

            session.set_status('running')

            self.take_data = True

            data_counter = {'timestamps':[], 'block_name':'HWPEncoder_counter','data':{}}
            data_irig = {'timestamp':time.time(), 'block_name':'HWPEncoder_irig','data':{}}
            while self.take_data:
                self.ep.grab_and_parse_data()
                while len(self.ep.irig_queue):
                    lastdata_counter = data_counter
                    data_counter = {'timestamps':[], 'block_name':'HWPEncoder_counter','data':{}}
                    counter_list = []
                    counter_index_list = []
                    while len(self.ep.counter_queue):
                        counter_data = self.ep.counter_queue.popleft()
                        counter_list += counter_data[0].tolist()
                        counter_index_list += counter_data[1].tolist()
                    # This timestamps are 1-D counte_list length numpy array of the same timestamp of curren time
                    data_counter['timestamps'] = numpy.ones(len(counter_list)) * time.time()
                    data_counter['data']['counter'] = counter_list
                    data_counter['data']['counter_index'] = counter_index_list

                    data_quad = {'timestamps':[], 'block_name':'HWPEncoder_quad','data':{}}
                    quad_list = []
                    while len(self.ep.quad_queue):
                        quad_data = self.ep.quad_queue.popleft()
                        quad_list.append(quad_data)
                    data_quad['timestamps'] = numpy.ones(len(quad_list)) * time.time()
                    data_quad['data']['quad'] = quad_list

                    irig_data = self.ep.irig_queue.popleft()
                    rising_edge_time = irig_data[0]
                    irig_time = irig_data[1]
                    irig_info = irig_data[2]
                    synch_pulse_clock_times = irig_data[3]
                    
                    lastdata_irig = data_irig
                    data_irig = {'timestamp':time.time(), 'block_name':'HWPEncoder_irig', 'data':{}}
                    data_irig['data']['irig_time'] = irig_time
                    data_irig['data']['rising_edge_time'] = rising_edge_time
                    data_irig['data']['irig_sec'] = de_irig(irig_info[0], 1)
                    data_irig['data']['irig_min'] = de_irig(irig_info[1], 0)
                    data_irig['data']['irig_hour'] = de_irig(irig_info[2], 0)
                    data_irig['data']['irig_day'] = de_irig(irig_info[3], 0) + de_irig(irig_info[4], 0) * 100
                    data_irig['data']['irig_year'] = de_irig(irig_info[5], 0)
                    for i in range(10):
                        data_irig['data']['irig_synch_pulse_clock_times_%d'%i] = synch_pulse_clock_times[i]
                    # For rough estimation of HWP rotation frequency
                    if 'rising_edge_time' in lastdata_irig['data'] and \
                       'counter' in lastdata_counter['data'] and len(data_counter['data']['counter']):
                        
                        dsec = data_irig['data']['irig_time'] - lastdata_irig['data']['irig_time']
                        dclock_sec = data_irig['data']['rising_edge_time'] - lastdata_irig['data']['rising_edge_time']
                        dclock_counter = data_counter['data']['counter'][-1] - data_counter['data']['counter'][0]
                        dindex_counter = data_counter['data']['counter_index'][-1] - data_counter['data']['counter_index'][0]
                        pulse_rate = dindex_counter / dclock_counter * dclock_sec / dsec
                        hwp_freq = pulse_rate / 2. / NUM_SLITS
                        print('pulse_rate', pulse_rate, hwp_freq)
                        data_irig['data']['approx_hwp_freq'] = hwp_freq
                    else:
                        data_irig['data']['approx_hwp_freq'] = 0.

                    self.agent.publish_to_feed('HWPEncoder_counter', data_counter)
                    self.agent.publish_to_feed('HWPEncoder_irig', data_irig)
                    self.agent.publish_to_feed('HWPEncoder_quad', data_quad)

                    self.agent.feeds['HWPEncoder_counter'].flush_buffer()
                    self.agent.feeds['HWPEncoder_irig'].flush_buffer()
                    self.agent.feeds['HWPEncoder_quad'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'

# Portion of the code that runs
if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    
    args = parser.parse_args()

    site_config.reparse_args(args, 'HWPBBBAgent')

    agent, runner = ocs_agent.init_site_agent(args)
    
    hwp_bbb_agent = HWPBBBAgent(agent)

    agent.register_process('acq', hwp_bbb_agent.start_acq, hwp_bbb_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
            
