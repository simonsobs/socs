from __future__ import print_function
from labjack import ljm
from slowdaq.pb2 import *
import slowdaq.netarray as narr
import numpy as np
import time
import calendar
import signal
import sys
from sys import stderr
from datetime import datetime
from multiprocessing import Process, ProcessError
from multiprocessing.queues import SimpleQueue

# IRIG-B constants
MS_MARKER = 0.008
MS_BITZERO = 0.002
MS_BITONE = 0.005
MS_BITMARGIN = 0.0005

DEBUG = False

# Enable print to stderr
def eprint(*args, **kwargs):
    print(*args, file=stderr, **kwargs)

# debug print
def dprint(*args, **kwargs):
    if DEBUG:
        eprint(*args, **kwargs)

# these functions are from libtimecode.py
def smhdy_bit(iarray):
    vec = np.array([1, 2, 4, 8, 0, 10, 20, 40, 80, 0, 100, 200])#12
    smhdy = np.inner(vec, iarray)
    return smhdy

def calc_smhdy(segone):
    # sec
    smhdy_vec = np.zeros(12, dtype=int)
    smhdy_vec[:8] = segone[0:8]
    seconds = smhdy_bit(smhdy_vec)
    # min
    smhdy_vec = np.zeros(12, dtype=int)
    smhdy_vec[:8] = segone[9:17]
    minutes = smhdy_bit(smhdy_vec)
    # hour
    smhdy_vec = np.zeros(12, dtype=int)
    smhdy_vec[:8] = segone[19:27]
    hours = smhdy_bit(smhdy_vec)
    # day
    smhdy_vec = np.zeros(12, dtype=int)
    smhdy_vec[:] = segone[29:41]
    days = smhdy_bit(smhdy_vec)
    # years
    smhdy_vec = np.zeros(12, dtype=int)
    smhdy_vec[:8] = segone[49:57]
    years = smhdy_bit(smhdy_vec)
    st = time.strptime('%02d:%d:%d:%d:%d'%(years, days, hours, minutes, seconds), \
        '%y:%j:%H:%M:%S')
    tepoch = calendar.timegm(st)
    return tepoch

class T7Publisher():

    def __init__(self, name, agg_addr, agg_port, debug = False,
                 daqid = None, scan_rate = -1, scan_port = [], 
                 fio_state = False, scale = 1):
        """initialize a T7 publisher. Publisher parameters need to be provided,
        but DAQ parameters are optional and can be set later.

        Arguments: (For Publisher)
            name {str} -- name of this publisher
            agg_addr {str} -- ip address of the aggregater
            agg_port {int} -- port of the aggregater

        Keyword Arguments: (Mostly for DAQ)
            debug {bool} -- Debug option. Enables the debug flag of the Publisher
                            module as well as this module (which is a lot of
                            information.) The debug message of this module
                            will be printed to stderr (default: {False})
            daqid {int} -- id of the daq to be controlled. Could be an ip address,
                           an actual ID of the DAQ, or "ANY". See labjack document
                           for more details. (default: {None})
            scan_rate {number} -- scan rate of the DAQ (default: {-1})
            scan_port {list} -- list of analog port names to be scanned. Notice
                                that FIO_STATE is ALWAYS included in the list
                                of scan ports so should not be added in this parameter
                                otherwise error will occur. (default: {[]})
            fio_state {bool} -- publish the entire fio_state or not.
            scale {int} -- analog data scaling down. If is not 1, when data 
                           are published, @scale number of data will be 
                           downscaled (averaged) to one data.

        """
        DEBUG = debug

        self.pub = Publisher(name, agg_addr, agg_port, debug)

        self.daqid = daqid
        self.scan_rate = scan_rate
        self.dt_sample = 1 / scan_rate      # time of each sample

        self.scan_port = ["FIO_STATE"]
        self.scan_port.extend(scan_port)    # FIO_STATE + whatever analog ports

        self.num_port = len(self.scan_port)
        dprint(self.scan_port)

        self.scale = scale

        # open the DAQ if daq parameters are specified.
        if self.daqid:
            try:
                self.handle = ljm.openS("T7", "ANY", daqid)
                info = ljm.getHandleInfo(self.handle)
                eprint("Opened a LabJack with Device type: %i, Connection type: %i,\n" \
                    "Serial number: %i, IP address: %s, Port: %i,\nMax bytes per MB: %i" % \
                    (info[0], info[1], info[2], ljm.numberToIP(info[3]), info[4], info[5]))
            except:
                eprint("Error opening DAQ. Check id.")
                self.handle = None
        else:
            self.handle = None

        self.signaled = False
        self.fifo_buf = None
        self.data_buf = [ [] for i in range(self.num_port - 1) ]
        
        self.fio_state_buf = [] if fio_state else None

        self.index = 0


    def __del__(self):
        """Destructor. Ensures handle is closed properly.
        """
        from labjack import ljm
        if self.handle:
            ljm.close(self.handle)

    @staticmethod
    def debug_mode(mode):
        """Turning on or off the debug mode for output
        Arguments:
            mode {bool} -- True for on, False for off.
        """
        DEBUG = mode

    def set_signal(self):
        """For signal (SIGINT, etc.) handling
        """
        self.signaled = True

    def set_daq(self, daqid, scan_rate, scan_port):
        """Set the DAQ parameters. Can be used to reset an initialized object.

        Arguments:
            daqid {int} -- id of the daq to be controlled. Could be an ip address,
                           an actual ID of the DAQ, or "ANY". See labjack document
                           for more details.
            scan_rate {number} -- scan rate of the DAQ
            scan_port {list} -- list of analog port names to be scanned. Notice
                                that FIO_STATE is ALWAYS included in the list
                                of scan ports so should not be added in this parameter
                                otherwise error will occur.
        """
        if self.handle:
            ljm.close(self.handle)

        self.daqid = daqid
        self.scan_rate = scan_rate
        self.scan_port = ["FIO_STATE"].entend(scan_port)
        print(self.scan_port)

        try:
            self.handle = ljm.open("T7", "ANY", daqid)
            eprint("Opened a LabJack with Device type: %i, Connection type: %i,\n" \
                    "Serial number: %i, IP address: %s, Port: %i,\nMax bytes per MB: %i" % \
                    (info[0], info[1], info[2], ljm.numberToIP(info[3]), info[4], info[5]))
        except:
            eprint("Error opening DAQ. Check id.")
            self.handle = None

    def add_port(self, port):
        """Add an analog port to the scan list.

        Arguments:
            port {str} -- port to be added. Repetition will be checked, but
                          validity will not.
        """
        if (port not in self.scan_port):
            self.scan_port.append(port)

    def stream(self, scans_per_read=-1, max_request=-1):
        """Scans @self.scan_ports and publish the scanned data, with decoded
        IRIG-B timestamps on each published data. The publishing is done by
        initiating a process that runs until stream stops and all data read have
        been published. The scanned data is transfered by a SimpleQueue data
        structure for this single-producer, single-consumer program.
        To ensure the SimpleQueue will not block forever, a "None" will be put
        into it when the streaming stops.

        Keyword Arguments:
            scans_per_read {number} -- scans per read needed for T7 streaming.
                                       If not specified, will be defaulted to
                                       scanrate/10 (default: {-1})
            max_request {number} -- Maximum requests to stream. Each request
                                    corresponds to one read.
                                    If not specified, will run indefinitely until
                                    signaled. (default: {-1})
        """

        if self.handle == None:
            eprint("Error: DAQ not set up.")
            return

        # signal handling.
        self.signaled = False
        # stores the original signals
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sighup = signal.getsignal(signal.SIGHUP)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        # set the new signal handlers
        signal.signal(signal.SIGINT, lambda s, f: self.set_signal())
        signal.signal(signal.SIGHUP, lambda s, f: self.set_signal())
        signal.signal(signal.SIGTERM, lambda s, f: self.set_signal())

        # Some code are provided by LabJack's sample program (stream_basic.py)
        handle = self.handle
        aScanListNames = self.scan_port #Scan list names to stream
        numAddresses = len(aScanListNames)
        aScanList = ljm.namesToAddresses(numAddresses, aScanListNames)[0]
        scanRate = self.scan_rate
        scansPerRead = int(scanRate/10) if scans_per_read == -1 else scans_per_read

        self.fifo_buf = SimpleQueue()  # reset buffer

        # First try to stop stream mode just in case the labjack is already running that mode.
        try:
            ljm.eStreamStop(handle)
        except ljm.LJMError:
            print("\Failed to stop the stream mode. Maybe ok to ignore this message...")

        try:

            # XXX: change DAQ configuration as need!
            #aNames = ["STREAM_BUFFER_SIZE_BYTES", "AIN0_NEGATIVE_CH", "AIN2_NEGATIVE_CH"]
            #aValues = [32768, 1, 3]
            aNames = ["STREAM_BUFFER_SIZE_BYTES", "AIN_ALL_NEGATIVE_CH"]
            aValues = [32768, 1]
            ljm.eWriteNames(handle, len(aNames), aNames, aValues)

            # Configure and start stream
            scanRate = ljm.eStreamStart(handle, scansPerRead, numAddresses, aScanList, scanRate)
            eprint("\nStream started with a scan rate of %0.0f Hz." % scanRate)

            eprint("\nPerforming stream reads.")
            start = datetime.now()
            totScans = 0
            totSkip = 0    # Total skipped samples

            # start the publishing thread
            p = Process(target = self.publisher_proc)
            p.start()

            # loop that does the read
            i = 1
            while ((i <= max_request or max_request == -1) and not self.signaled):
                ret = ljm.eStreamRead(handle)

                data = ret[0]
                scans = len(data)/numAddresses
                totScans += scans

                # Count the skipped samples which are indicated by -9999 values. Missed
                # samples occur after a device's stream buffer overflows and are
                # reported after auto-recover mode ends.
                curSkip = data.count(-9999.0)
                totSkip += curSkip

                for d in data:
                    self.fifo_buf.put(d)

                # print out in LJM's library. Good for debug but should be
                # commented out latter.
                if DEBUG:
                    eprint("\neStreamRead %i" % i)
                    ainStr = ""
                    for j in range(0, numAddresses):
                        ainStr += "%s = %0.5f " % (aScanListNames[j], data[j])
                    eprint("  1st scan out of %i: %s" % (scans, ainStr))
                    eprint("  Scans Skipped = %0.0f, Scan Backlogs: Device = %i, LJM = " \
                          "%i" % (curSkip/numAddresses, ret[1], ret[2]))
                i += 1

            ljm.eStreamStop(handle)
            eprint("Stream stopped")

            # Put the "None signal"
            self.fifo_buf.put(None)
            end = datetime.now()

            # wait for all the data in self.fifo_buf are published
            p.join()
            dprint("DEBUG: publisher process joined.")

            # delete this buffer
            del self.fifo_buf

            # restore the original handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGHUP, original_sighup)
            signal.signal(signal.SIGTERM, original_sigterm)

            eprint("\nTotal scans = %i" % (totScans))
            tt = (end-start).seconds + float((end-start).microseconds)/1000000
            eprint("Time taken = %f seconds" % (tt))
            eprint("LJM Scan Rate = %f scans/second" % (scanRate))
            eprint("Timed Scan Rate = %f scans/second" % (totScans/tt))
            eprint("Timed Sample Rate = %f samples/second" % (totScans*numAddresses/tt))
            eprint("Skipped scans = %0.0f" % (totSkip/numAddresses))

        # LabJack error
        except ljm.LJMError:
            ljme = sys.exc_info()[1]
            self.fifo_buf.put(None)
            p.join()
            del self.fifo_buf
            eprint(ljme)

        # general error
        except Exception:
            e = sys.exc_info()[1]
            self.fifo_buf.put(None)
            p.join()
            del self.fifo_buf
            print(e)


    def publisher_proc(self):
        """ publisher process. Decodes the IRIG-B code, publish the information.
        Runs as a separate process from the streamer, and uses a shared
        SimpleQueue structure.
        """
        eprint("Publisher process initiated.")

        irig_high_count = 0     # count of high bits
        irig_bits = []          # bits of irig signal
        irig_complete = False   # if an irig signal is completed
        irig_fall_processed = False # if an edge fall has been processed
        irig_raise_processed = False
        irig_time = -1          # decoded irig-b signal, transfered to unix time

        # safety...
        try:
            while True:
                # blocks if there's not any.
                data = self.fifo_buf.get()

                # exit condition
                if data is None:
                    break

                if self.fio_state_buf is not None:
                    self.fio_state_buf.append(data)

                # The scan is guaranteed to start with FIO_STATE, so we start by
                # decoding that.

                # decode IRIG signal
                data = int(data)&0x1
                if data == 1:
                    irig_high_count += 1
                    irig_fall_processed = False
                    if not irig_raise_processed:
                        irig_raise_processed = True
                    dprint("DEBUG: High bit count added.")

                elif data == 0 and not irig_fall_processed:
                    # there is a fall, a run is completed and assert this bit
                    # these code are from libtimecode.py
                    dprint("DEBUG: Falling edge caught. irig_high_count = {:d}, self.dt_sample = {:f}, product =  {:f}".\
                        format(irig_high_count, self.dt_sample, irig_high_count * self.dt_sample))
                    if MS_BITZERO - MS_BITMARGIN < irig_high_count * self.dt_sample < MS_BITZERO + MS_BITMARGIN:
                        irig_bits.append(0)
                        dprint("DEBUG: 0 appended to irig_bits")
                    elif MS_BITONE - MS_BITMARGIN < irig_high_count * self.dt_sample < MS_BITONE + MS_BITMARGIN:
                        irig_bits.append(1)
                        dprint("DEBUG: 1 appended to irig_bits")
                    elif MS_MARKER - MS_BITMARGIN < irig_high_count * self.dt_sample < MS_MARKER + MS_BITMARGIN:
                        if (len(irig_bits) != 0) and (irig_bits[-1] == 2):
                            # continuous run of marker bits, end / start of signal
                            irig_complete = True
                            dprint("DEBUG: IRIG signal hit two marker bit, completed...")
                        irig_bits.append(2)
                        dprint("DEBUG: 2 appended to irig_bits")
                    else:
                        eprint("ERROR: unidentified bit in IRIG signal.")
                    irig_fall_processed = True
                    irig_raise_processed = False
                    irig_high_count = 0


                # if a complete is marked, decode this irig_b signal
                if irig_complete and irig_raise_processed:

                    # new mechanism: publish the data only when the IRIG time code
                    # changes, in a net-array format. Otherwise the data are 
                    # being buffered as a list. The published data has the format:
                    # {"timecode": Decoded IRIG timecode as unix time {int},
                    #  [port name](string): a net array representing the data from the port as the key.
                    #  [port name](string): ...
                    # }
                    self.publish_data_buff(irig_time)

                    if len(irig_bits) != 100:
                        eprint("Warning: invalid IRIG-B frame (len(irig_bits)={:d}, reporting using last frame...".\
                            format(len(irig_bits)))
                    else:
                        irig_time = calc_smhdy(irig_bits)
                        dprint("DEBUG: calculated irig_time: {:d}".format(irig_time))
                    irig_bits[:] = []
                    irig_complete = False

                # append each data to the buffer.
                # returns false when a None is captured (end of transmission signaled)
                if not self.append_round():
                    break

            ### END WHILE LOOP
            eprint("Publisher process ended gracefully.")

        except Exception:
            eprint("Exception caught in publisher process.")
            self.signaled = True
            e = sys.exc_info()[1]
            eprint(e)
            raise ProcessError("Exception caught in publisher process.")

    def append_round(self):
        """ append self.num_port - 1 data from self.fifo_buf, to the appropriate
        data buffer. self.data_buf is implemented as a list of list
        for convenient resizing.

        Returns:
            bool -- False if a "None" is caught (hence the streaming has stopped),
                    True otherwise
        """
        for i in range(self.num_port - 1):
            data = self.fifo_buf.get()

            # exit condition
            if data is None:
                return False

            self.data_buf[i].append(data)

        return True

    def publish_data_buff(self, irig_time):
        """Publish the entire data buffer. All ports will be published at once
        separately. The published json has the following format:
        {"timecode": Decoded IRIG timecode as unix time {int},
         [port name](string): a net array representing the data from the port as the key.
         [port name](string): ...
        }
        
        Argument:
            irig_time {int} -- Decoded IRIG timecode for these data.
        """
        pub_data = {"timecode": irig_time, 'time': time.time(), 'index': self.index}

        for i in range(self.num_port - 1):
            # ignore -1 irig_time
            if irig_time != -1:

                # downscaling.
                downscaled = []
                if self.scale != 1:

                    counter = 0
                    total = 0

                    for d in self.data_buf[i]:
                        if counter == self.scale:
                            downscaled.append(total/self.scale)
                            total = 0
                            counter = 0
                        counter += 1
                        total += d
                    # last round
                    downscaled.append(total/counter)
                else:
                    downscaled = self.data_buf[i]

                #darr = np.array(downscaled).astype('float32') # use float64 if needed.
                darr = np.array(downscaled).astype('float16') # use float64 if needed.
                netarr = narr.np_serialize(darr)    # netarray

                pub_data[ self.scan_port[i + 1] ] = netarr 

                dprint("DEBUG: {:d} data from {:s} with timecode {:d} were queued.".\
                    format(len(darr), self.scan_port[i + 1], irig_time))
            # clear data buffer
            self.data_buf[i][:] = []

        # publish FIO_STATE if needed
        if self.fio_state_buf is not None:
            darr = np.array(self.fio_state_buf).astype('float32') # use float64 if needed.
            netarr = narr.np_serialize(darr)    # netarray
            
            pub_data["FIO_STATE"] = netarr 

            dprint("DEBUG: {:d} data from {:s} with timecode {:d} were queued.".\
                format(len(darr), "FIO_STATE", irig_time))
            self.fio_state_buf[:] = []

        data = self.pub.pack(pub_data)
        self.pub.queue(data)
        self.index += 1
        # actually publish the data
        self.pub.serve()
        dprint("DEBUG: Serve called.")










