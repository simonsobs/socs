"""OCS agent module to read the data from beagleboneblack for CHWP encoder

Note
----
   This is confirmed to be work with the following versions of beagleboneblack software:
   - currently hwpdaq branch in spt3g_software_sa repository: 731ff39
   (sha256sum)
   - Encoder1.bin: c8281525bdd0efae66aede7cffc3520ab719cfd67f6c2d7fd01509a4289a9d32
   - Encoder2.bin: a6ed9d89e9cf26036bf1da9e7e2098da85bbfa6eb08d0caef1e3c40877dd5077
   - IRIG1.bin: 7bc37b30a1759eb792f0db176bcd6080f9c3c7ec78ba2e1614166b2031416091
   - IRIG2.bin: d206dd075f73c32684d8319c9ed19f019cc705a9f253725de085eb511b8c0a12

Data feeds
----------
HWPEncoder:
   (HWPEncoder_counter_sub)
   counter_sub: subsampled counter values [::NUM_SUBSAMPLE]
   counter_index_sub: subsampled index counter values

   (HWPEncoder_freq)
   approx_hwp_freq: approximate estimate of hwp rotation frequency
   diff_counter_mean: mean of diff(counter)
   diff_index_mean: mean of diff(counter_index)
   diff_counter_std: std of diff(counter)
   diff_index_std: std of diff(counter_index)

   (HWPEncoder_quad)
   quad: quadrature data

   (HWPEncoder_irig)
   irig_time: decoded time in second since the unix epoch
   irig_minus_sys: difference between irig time and system time in second
   rising_edge_cont: BBB clcok count values
                     for the IRIG on-time reference marker risinge edge
   irig_sec: seconds decoded from IRIG-B
   irig_min: minutes decoded from IRIG-B
   irig_hour: hours decoded from IRIG-B
   irig_day: days decoded from IRIG-B
   irig_year: years decoded from IRIG-B
   bbb_clock_freq: BBB clock frequency estimate using IRIG-B

   (HWPEncoder_irig_raw)
   irig_synch_pulse_clock_time: reference marker time in sec
   irig_synch_pulse_clock_counts: clock counts for reference markers
   irig_info: IRIG bit info

HWPEncoder_full: separated feed for full-sample HWP encoder data,
                 not to be included in influxdb database
   (HWPEncoder_counter)
   counter: BBB counter values for encoder signal edges
   counter_index: index numbers for detected edges by BBB
"""

import argparse
import calendar
import os
import select
import socket
import struct
import time
from collections import deque

import numpy as np
import txaio

txaio.use_twisted()

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# These three values (COUNTER_INFO_LENGTH, COUNTER_PACKET_SIZE, IRIG_PACKET_SIZE)
# should be consistent with the software on beaglebone.
# The number of datapoints in every encoder packet from the Beaglebone
COUNTER_INFO_LENGTH = 120
# The size of the encoder packet from the beaglebone
#    (header + 3*COUNTER_INFO_LENGTH datapoint information + 1 quadrature readout)
COUNTER_PACKET_SIZE = 4 + 4 * COUNTER_INFO_LENGTH + 8 * COUNTER_INFO_LENGTH + 4
# The size of the IRIG packet from the Beaglebone
IRIG_PACKET_SIZE = 132

# The slit scaler value for rough HWP rotating frequency
NUM_SLITS = 570
# Number of encoder counter samples to publish at once
NUM_ENCODER_TO_PUBLISH = 4200
# Seconds to publish encoder data even before reaching NUM_ENCODER_TO_PUBLISH
SEC_ENCODER_TO_PUBLISH = 10
# Subsampling facot for the encoder counter data to influxdb
NUM_SUBSAMPLE = 500


def de_irig(val, base_shift=0):
    """Converts the IRIG signal into sec/min/hours/day/year depending on the parameters

    Parameters
    ----------
    val : int
       raw IRIG bit info of each 100msec chunk
    base_shift : int, optional
       number of bit shifts. This should be 0 except for seccods

    Returns
    -------
    int
       Either of sec/min/hourds/day/year

    """
    return (((val >> (0 + base_shift)) & 1)
            + ((val >> (1 + base_shift)) & 1) * 2
            + ((val >> (2 + base_shift)) & 1) * 4
            + ((val >> (3 + base_shift)) & 1) * 8
            + ((val >> (5 + base_shift)) & 1) * 10
            + ((val >> (6 + base_shift)) & 1) * 20
            + ((val >> (7 + base_shift)) & 1) * 40
            + ((val >> (8 + base_shift)) & 1) * 80)


def count2time(counts, t_offset=0.):
    """Quick etimation of time using Beagleboneblack clock counts

    Parameters
    ----------
    counts : list of int
       Beagleboneblack clock counter value
    t_offset : int, optional
       time offset in seconds

    Returns
    -------
    list of float
       Estimated time in seconds assuming the Beagleboneblack clock frequency is 200 MHz.
       Without specifying t_offset, output is just the difference
       from the first sample in the input list

    """
    t_array = np.array(counts, dtype=float) - counts[0]
    # Assuming BBB clock is 200MHz
    t_array *= 5.e-9
    t_array += t_offset

    return t_array.tolist()


class EncoderParser:
    """Class which will parse the incoming packets from the BeagleboneBlack and store the data

    Attributes
    ----------
    counter_queue : deque object
       deque to store the encoder counter data
    irig_queue : deque object
       deque to store the IRIG data
    is_start : int
       Used for procedures that only run when data collection begins
       Initialized to be 1, until the first IRIG parsing happens and set to 0
    start_time : list of int
       Will hold the time at which data collection started [hours, mins, secs]
    current_time : int
       Current unix timestamp in seconds parased from IRIG
    sock : scoket.sock
       a UDP socket to connect to the Beagleboneblack
    data : str
       String which will hold the raw data from the Beaglebone before it is parsed
    read_chunk_size : int
       Maximum data size to receive UDP packets in bytes

   Parameters
    ----------
    beaglebone_port : int, optional
       Port number to receive UDP packets from Beagleboneblack
       This must be the same as the localPort in the Beaglebone code
    read_chunk_size : int, optional
       Maximum data size to receive UDP packets in bytes
       read_chunk_size: This value shouldn't need to change

    """

    def __init__(self, beaglebone_port=8080, read_chunk_size=8196):
        # Creates twoe queues to hold the data from the encoder, IRIG, and quadrature respectively
        self.counter_queue = deque()
        self.irig_queue = deque()

        # Used for procedures that only run when data collection begins
        self.is_start = 1
        # Will hold the time at which data collection started [hours, mins, secs]
        self.start_time = [0, 0, 0]
        # Will be continually updated with unix in seconds
        self.current_time = 0

        # If True, will stop trying to read data from socket
        self.stop = False

        # Creates a UDP socket to connect to the Beaglebone
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # This helps with testing and rebinding to the same port after reset...
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Binds the socket to a specific ip address and port
        # The ip address can be blank for accepting any UDP packet to the port
        self.sock.bind(('', beaglebone_port))
        # self.sock.setblocking(0)

        # String which will hold the raw data from the Beaglebone before it is parsed
        self.data = ''
        self.read_chunk_size = read_chunk_size

        self.log = txaio.make_logger()

    def pretty_print_irig_info(self, irig_info, edge, print_out=False):
        """Takes the IRIG information, prints it to the screen, sets the current time,
        and returns the current time

        Parameters
        ----------
        irig_info : list of int
           IRIG bit info
        edge : int
           Clock count of rising edge of a reference marker bit
        print_out : bool, optional
           Set True to print out the parsed timestamp

        Returns
        -------
        current_time : int
           Current unix timestamp in seconds parased from IRIG

        """
        # Calls self.de_irig() to get the sec/min/hour of the IRIG packet
        secs = de_irig(irig_info[0], 1)
        mins = de_irig(irig_info[1], 0)
        hours = de_irig(irig_info[2], 0)
        day = de_irig(irig_info[3], 0) \
            + de_irig(irig_info[4], 0) * 100
        year = de_irig(irig_info[5], 0)

        # If it is the first time that the function is called then set self.start_time
        # to the current time
        if self.is_start == 1:
            self.start_time = [hours, mins, secs]
            self.is_start = 0

        if print_out:
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

            # Print UTC time, run time, and current clock count of the beaglebone
            print('Current Time:', ('%d:%d:%d' % (hours, mins, secs)),
                  'Run Time', ('%d:%d:%d' % (dhours, dmins, dsecs)),
                  'Clock Count', edge)

        # Set the current time in seconds (changed to seconds from unix epoch)
        # self.current_time = secs + mins*60 + hours*3600
        try:
            st_time = time.strptime("%d %d %d:%d:%d" % (year, day, hours, mins, secs),
                                    "%y %j %H:%M:%S")
            self.current_time = calendar.timegm(st_time)
        except ValueError:
            self.log.error(f'Invalid IRIG-B timestamp: {year} {day} {hours} {mins} {secs}')
            self.current_time = -1

        return self.current_time

    def check_data_length(self, start_index, size_of_read):
        """Checks to make sure that self.data is the right size
        Return false if the wrong size, return true if the data is the right size

        Parameters
        ----------
        start_index : int
           first index of the data to read
        size_of_read : int
           data size to read in bytes

        Returns
        -------
        bool
           False if the current data size is smaller than the data size suggested by the header info

        """
        if start_index + size_of_read > len(self.data):
            self.data = self.data[start_index:]
            return False

        return True

    def grab_and_parse_data(self):
        """Grabs self.data, determine what packet it corresponds to, parses the data.
        This is a while loop to look for an appropriate header in a packet from beaglebone.
        Then, the data will be passed to an appropriate parsing method
        and stored in either of counter_queue or irig_queue.
        The detailed structure of the queues can be found in parse_counter_info/parse_irig_info.

        If unexpected data length found, this will output some messages:
           Error 0: data length is shorter than the header size (4 bytes)
           Error 1: data length is shorter than the encoder counter info
                    even though the encoder packet header is found.
           Error 2: data length is shorter than the IRIG info
                    even though the IRIG packet header is found.
        """
        self.stop = False

        while not self.stop:  # This can be toggled by encoder agent to unblock
            # If there is data from the socket attached to the beaglebone then
            #     ready[0] = true
            # If not then continue checking for 2 seconds and if there is still no data
            #     ready[0] = false
            ready = select.select([self.sock], [], [], 2)
            if ready[0]:
                # Add the data from the socket attached to the beaglebone
                # to the self.data string
                data = self.sock.recv(self.read_chunk_size)
                if len(self.data) > 0:
                    self.data += data
                else:
                    self.data = data

                while True:
                    # Check to make sure that there is at least 1 int in the packet
                    # The first int in every packet should be the header
                    if not self.check_data_length(0, 4):
                        self.log.error('Error 0')
                        break

                    header = self.data[0:4]
                    # Convert a structure value from the beaglebone (header) to an int
                    header = struct.unpack('<I', header)[0]
                    # print('header ', '0x%x'%header)

                    # 0x1EAF = Encoder Packet
                    # 0xCAFE = IRIG Packet
                    # 0xE12A = Error Packet

                    # Encoder
                    if header == 0x1eaf:
                        # Make sure the data is the correct length for an Encoder Packet
                        if not self.check_data_length(0, COUNTER_PACKET_SIZE):
                            self.log.error('Error 1')
                            break
                        # Call the meathod self.parse_counter_info() to parse the Encoder Packet
                        self.parse_counter_info(self.data[4: COUNTER_PACKET_SIZE])
                        if len(self.data) >= COUNTER_PACKET_SIZE:
                            self.data = self.data[COUNTER_PACKET_SIZE:]

                    # IRIG
                    elif header == 0xcafe:
                        # Make sure the data is the correct length for an IRIG Packet
                        if not self.check_data_length(0, IRIG_PACKET_SIZE):
                            self.log.error('Error 2')
                            break
                        # Call the meathod self.parse_irig_info() to parse the IRIG Packet
                        self.parse_irig_info(self.data[4: IRIG_PACKET_SIZE])
                        if len(self.data) >= IRIG_PACKET_SIZE:
                            self.data = self.data[IRIG_PACKET_SIZE:]

                    # Error
                    # An Error Packet will be sent if there is a timing error in the
                    # synchronization pulses of the IRIG packet
                    # If you see 'Packet Error' check to make sure the IRIG is functioning as
                    # intended and that all the connections are made correctly
                    elif header == 0xe12a:
                        self.log.error('Packet Error')
                        # Clear self.data
                        self.data = ''
                    elif header == 0x1234:
                        # Expected behavior when HWP is not spinning
                        self.log.debug('Received timeout packet.')
                        # Clear self.data
                        self.data = ''
                    else:
                        self.log.error('Bad header')
                        # Clear self.data
                        self.data = ''

                    if len(self.data) == 0:
                        break
                break

            # If there is no data from the beaglebone 'Looking for data ...' will print
            # If you see this make sure that the beaglebone has been set up properly
            # print('Looking for data ...')

    def parse_counter_info(self, data):
        """Method to parse the Encoder Packet and put them to counter_queue

        Parameters
        ----------
        data : str
           string for the encoder ounter info

        Note:
           'data' structure:
           (Please note that '150' below might be replaced by COUNTER_INFO_LENGTH)
           [0] Readout from the quadrature
           [1-150] clock counts of 150 data points
           [151-300] corresponding clock overflow of the 150 data points (each overflow count
           is equal to 2^16 clock counts)
           [301-450] corresponding absolute number of the 150 data points ((1, 2, 3, etc ...)
           or (150, 151, 152, etc ...) or (301, 302, 303, etc ...) etc ...)

           counter_queue structure:
           counter_queue = [[64 bit clock counts],
                            [clock count indicese incremented by every edge],
                            quadrature,
                            current system time]
        """

        # Convert the Encoder Packet structure into a numpy array
        derter = np.array(struct.unpack('<' + 'I' + 'III' * COUNTER_INFO_LENGTH, data))

        # self.quad_queue.append(derter[0].item()) # merged to counter_queue
        self.counter_queue.append((derter[1:COUNTER_INFO_LENGTH + 1]
                                   + (derter[COUNTER_INFO_LENGTH + 1:2 * COUNTER_INFO_LENGTH + 1] << 32),
                                   derter[2 * COUNTER_INFO_LENGTH + 1:3 * COUNTER_INFO_LENGTH + 1],
                                   derter[0].item(), time.time()))

    def parse_irig_info(self, data):
        """Method to parse the IRIG Packet and put them to the irig_queue

        Parameters
        ----------
        data : str
           string for the IRIG info

        Note
        ----
           'data' structure:
           [0] clock count of the IRIG Packet which the UTC time corresponds to
           [1] overflow count of initial rising edge
           [2] binary encoding of the second data
           [3] binary encoding of the minute data
           [4] binary encoding of the hour data
           [5-11] additional IRIG information which we do mot use
           [12-21] synchronization pulse clock counts
           [22-31] overflow count at each synchronization pulse

           irig_queue structure:
           irig_queue = [Packet clock count,
                         Packet UTC time in sec,
                         [binary encoded IRIG data],
                         [synch pulses clock counts],
                         current system time]

        """

        # Convert the IRIG Packet structure into a numpy array
        unpacked_data = struct.unpack('<L' + 'L' + 'L' * 10 + 'L' * 10 + 'L' * 10, data)

        # Start of the packet clock count
        # overflow.append(unpacked_data[1])
        # print "overflow: ", overflow

        rising_edge_time = unpacked_data[0] + (unpacked_data[1] << 32)

        # Stores IRIG time data
        irig_info = unpacked_data[2:12]

        # Prints the time information and returns the current time in seconds
        irig_time = self.pretty_print_irig_info(irig_info, rising_edge_time)

        # Stores synch pulse clock counts accounting for overflow of 32 bit counter
        synch_pulse_clock_times = (np.asarray(unpacked_data[12:22])
                                   + (np.asarray(unpacked_data[22:32]) << 32)).tolist()

        # self.irig_queue = [Packet clock count,Packet UTC time in sec,
        #                    [binary encoded IRIG data],[synch pulses clock counts],
        #                    [current system time]]
        self.irig_queue.append((rising_edge_time, irig_time, irig_info,
                                synch_pulse_clock_times, time.time()))

    def __del__(self):
        self.sock.close()


class HWPBBBAgent:
    """OCS agent for HWP encoder DAQ using Beaglebone Black

    Attributes
    ----------
    rising_edge_count : int
       clock count values for the rising edge of IRIG reference marker,
       saved for calculating the beaglebone clock frequency
    irig_time : int
       unix timestamp from IRIG

    """

    def __init__(self, agent_obj, port=8080, ip='None'):
        self.active = True
        self.agent = agent_obj
        self.log = agent_obj.log
        self.lock = TimeoutLock()
        self.port = port
        self.ip = ip
        self.take_data = False
        self.initialized = False
        # For clock count to time conversion
        self.rising_edge_count = 0
        self.irig_time = 0

        self.last_quad = None
        self.last_quad_time = None

        agg_params = {'frame_length': 60}
        self.agent.register_feed('HWPEncoder', record=True,
                                 agg_params=agg_params)
        agg_params = {'frame_length': 60, 'exclude_influx': True}
        self.agent.register_feed('HWPEncoder_full', record=True,
                                 agg_params=agg_params)
        self.parser = EncoderParser(beaglebone_port=self.port)

    def restart(self, session, params):
        """restart()

        **Task** - Restarts the beaglebone process

        Notes:
            The most recent data collected is stored in the session data in the
            structure:

                >>> response.session['response']
                {'result': True,
                 'log': ["Restart command response: Success"]}
        """
        if self.ip == 'None':
            return False, "Could not restart process because beaglebone ip is not defined"

        _restart_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _restart_socket.connect((self.ip, 5656))
        _restart_socket.sendall(('reset\n').encode())
        time.sleep(0.5)

        resp = _restart_socket.recv(4096).decode().strip()
        log = f'Restart command response: {resp}'
        result = True if resp == "Success" else False
        _restart_socket.close()
        time.sleep(10)

        session.data['response'] = {'result': result, 'log': log}
        return result, f'Success: {result}'

    def acq(self, session, params):
        """acq()

        **Process** - Start acquiring data.

        """
        time_encoder_published = 0
        counter_list = []
        counter_index_list = []
        quad_list = []
        quad_counter_list = []
        received_time_list = []

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn('Could not start acq because {} is already running'
                              .format(self.lock.job))
                return False, 'Could not acquire lock.'

            self.take_data = True

            # Prepare data_cache for session.data
            self.hwp_freq = -1
            self.ct = time.time()
            data_cache = {
                'approx_hwp_freq': self.hwp_freq,
                'encoder_last_updated': self.ct,
                'irig_time': self.irig_time,
                'irig_last_updated': self.ct,
            }

            while self.take_data:
                # This is blocking until data are available
                self.parser.grab_and_parse_data()

                # IRIG data; normally every sec
                while len(self.parser.irig_queue):
                    irig_data = self.parser.irig_queue.popleft()
                    rising_edge_count = irig_data[0]
                    irig_time = irig_data[1]
                    irig_info = irig_data[2]
                    synch_pulse_clock_counts = irig_data[3]
                    sys_time = irig_data[4]
                    data = {'timestamp': sys_time, 'block_name': 'HWPEncoder_irig', 'data': {}}
                    data['data']['irig_time'] = irig_time
                    data['data']['irig_minus_sys'] = irig_time - sys_time
                    data['data']['rising_edge_count'] = rising_edge_count
                    data['data']['irig_sec'] = de_irig(irig_info[0], 1)
                    data['data']['irig_min'] = de_irig(irig_info[1], 0)
                    data['data']['irig_hour'] = de_irig(irig_info[2], 0)
                    data['data']['irig_day'] = de_irig(irig_info[3], 0) \
                        + de_irig(irig_info[4], 0) * 100
                    data['data']['irig_year'] = de_irig(irig_info[5], 0)

                    # Beagleboneblack clock frequency measured by IRIG
                    if self.rising_edge_count > 0 and irig_time > 0:
                        bbb_clock_freq = float(rising_edge_count - self.rising_edge_count) \
                            / (irig_time - self.irig_time)
                    else:
                        bbb_clock_freq = 0.
                    data['data']['bbb_clock_freq'] = bbb_clock_freq

                    self.agent.publish_to_feed('HWPEncoder', data)
                    self.rising_edge_count = rising_edge_count
                    self.irig_time = irig_time

                    # saving clock counts for every refernce edge and every irig bit info
                    data = {'timestamps': [], 'block_name': 'HWPEncoder_irig_raw', 'data': {}}
                    # 0.09: time difference in seconds b/w reference marker and
                    #       the first index marker
                    data['timestamps'] = sys_time + 0.09 + np.arange(10) * 0.1
                    data['data']['irig_synch_pulse_clock_time'] = list(irig_time + 0.09
                                                                       + np.arange(10) * 0.1)
                    data['data']['irig_synch_pulse_clock_counts'] = synch_pulse_clock_counts
                    data['data']['irig_info'] = list(irig_info)
                    self.agent.publish_to_feed('HWPEncoder', data)

                    data_cache['irig_time'] = self.irig_time
                    data_cache['irig_last_updated'] = sys_time
                    session.data.update(data_cache)

                # Reducing the packet size, less frequent publishing
                # Encoder data; packet coming rate = 570*2*2/150/4 ~ 4Hz packet at 2 Hz rotation
                while len(self.parser.counter_queue):
                    counter_data = self.parser.counter_queue.popleft()

                    counter_list += counter_data[0].tolist()
                    counter_index_list += counter_data[1].tolist()

                    quad_data = counter_data[2]
                    sys_time = counter_data[3]

                    received_time_list.append(sys_time)
                    quad_list.append(quad_data)
                    quad_counter_list.append(counter_data[0][0])
                    ct = time.time()

                    if len(counter_list) >= NUM_ENCODER_TO_PUBLISH \
                       or (len(counter_list)
                           and (ct - time_encoder_published) > SEC_ENCODER_TO_PUBLISH):
                        # Publishing quadratic data first
                        data = {'timestamps': [], 'block_name': 'HWPEncoder_quad', 'data': {}}
                        data['timestamps'] = received_time_list
                        data['data']['quad'] = quad_list
                        self.agent.publish_to_feed('HWPEncoder', data)
                        if quad_list:
                            self.last_quad = quad_list[-1]
                            self.last_quad_time = time.time()

                        # Publishing counter data
                        # (full sampled data will not be recorded in influxdb)
                        data = {'timestamps': [], 'block_name': 'HWPEncoder_counter', 'data': {}}
                        data['data']['counter'] = counter_list
                        data['data']['counter_index'] = counter_index_list

                        data['timestamps'] = count2time(counter_list, received_time_list[0])
                        self.agent.publish_to_feed('HWPEncoder_full', data)

                        # Subsampled data for influxdb display
                        data_subsampled = {'block_name': 'HWPEncoder_counter_sub', 'data': {}}
                        data_subsampled['timestamps'] = np.array(data['timestamps'])[::NUM_SUBSAMPLE].tolist()
                        data_subsampled['data']['counter_sub'] = np.array(counter_list)[::NUM_SUBSAMPLE].tolist()
                        data_subsampled['data']['counter_index_sub'] = np.array(counter_index_list)[::NUM_SUBSAMPLE].tolist()
                        self.agent.publish_to_feed('HWPEncoder', data_subsampled)

                        # For rough estimation of HWP rotation frequency
                        data = {'timestamp': received_time_list[0],
                                'block_name': 'HWPEncoder_freq', 'data': {}}
                        dclock_counter = counter_list[-1] - counter_list[0]
                        dindex_counter = counter_index_list[-1] - counter_index_list[0]
                        # Assuming Beagleboneblack clock is 200 MHz
                        pulse_rate = dindex_counter * 2.e8 / dclock_counter
                        hwp_freq = pulse_rate / 2. / NUM_SLITS

                        diff_counter = np.diff(counter_list)
                        diff_index = np.diff(counter_index_list)

                        self.log.debug(f'pulse_rate {pulse_rate} {hwp_freq}')
                        data['data']['approx_hwp_freq'] = hwp_freq
                        data['data']['diff_counter_mean'] = np.mean(diff_counter)
                        data['data']['diff_index_mean'] = np.mean(diff_index)
                        data['data']['diff_counter_std'] = np.std(diff_counter)
                        data['data']['diff_index_std'] = np.std(diff_index)
                        self.agent.publish_to_feed('HWPEncoder', data)

                        # Initialize lists
                        counter_list = []
                        counter_index_list = []
                        quad_list = []
                        quad_counter_list = []
                        received_time_list = []

                        time_encoder_published = ct

                        # Update session.data
                        self.hwp_freq = hwp_freq
                        self.ct = ct

                data_cache['approx_hwp_freq'] = self.hwp_freq
                data_cache['encoder_last_updated'] = self.ct
                data_cache['last_quad'] = self.last_quad
                data_cache['last_quad_time'] = self.last_quad_time
                session.data.update(data_cache)

        self.agent.feeds['HWPEncoder'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            self.parser.stop = True
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=int, default=8080,
                        help='Listening port of Agent for receiving UDP encoder packets. '
                             'This should match what is defined in the bbb encoder process configs')
    pgroup.add_argument('--ip', type=str, default='None',
                        help='IP of bbb running the corresponding encoder process')

    return parser


# Portion of the code that runs
def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPBBBAgent',
                                  parser=parser,
                                  args=args)
    agent, runner = ocs_agent.init_site_agent(args)
    hwp_bbb_agent = HWPBBBAgent(agent, port=args.port, ip=args.ip)
    agent.register_process('acq', hwp_bbb_agent.acq, hwp_bbb_agent._stop_acq, startup=True)
    agent.register_task('restart', hwp_bbb_agent.restart)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
