import argparse
import time
import struct
import os
import numexpr
import yaml
import csv
from scipy.interpolate import interp1d
import numpy as np
import txaio

from socs.signal_processing import FIRFilter

txaio.use_twisted()

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from labjack import ljm
    from labjack.ljm.ljm import LJMError
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


class LabJackFunctions:
    """
    Labjack helper class to provide unit conversion from analog input voltage
    """
    def __init__(self):
        self.log = txaio.make_logger()

    def unit_conversion(self, v_array, function_info):
        """
        Given a voltage array and function information from the
        labjack_config.yaml file, applies a unit conversion.
        Returns the converted value and its units.
        Args:
            v_array (numpy array): The voltages to be converted.
            function_info (dict): Specifies the type of function.
                If custom, also gives the function.
        """
        if function_info["user_defined"] == 'False':
            function = getattr(self, function_info['type'])
            return function(v_array)

        # Custom function evaluation
        else:
            units = function_info['units']
            new_values = []
            for v in v_array:
                new_values.append(float(numexpr.evaluate(function_info["function"])))
            return new_values, units

    def MKS390(self, v_array):
        """
        Conversion function for the MKS390 Micro-Ion ATM
        Modular Vaccum Gauge.
        """
        value = 1.3332*10**(2*v_array - 11)
        units = 'mBar'
        return value, units

    def warm_therm(self, v_array):
        """
        Conversion function for SO warm thermometry readout.
        Voltage is converted to resistance using the LJTick, which
        has a 2.5V supply and 10kOhm reference resistor. Resistance
        is converted to degrees Celsius using the calibration curve
        for the thermistor model, serial number 10K4D25.
        """
        # LJTick voltage to resistance conversion
        R = (2.5-v_array)*10000/v_array

        # Import the Ohms to Celsius cal curve and apply cubic
        # interpolation to find the temperature
        reader = csv.reader(open('cal_curves/GA10K4D25_cal_curve.txt'),
                            delimiter=' ')
        lists = [el for el in [row for row in reader]]
        T_cal = np.array([float(RT[0]) for RT in lists[1:]])
        R_cal = np.array([float(RT[1]) for RT in lists[1:]])
        T_cal = np.flip(T_cal)
        R_cal = np.flip(R_cal)
        try:
            RtoT = interp1d(R_cal, T_cal, kind='cubic')
            values = RtoT(R)

        except ValueError:
            self.log.error('Temperature outside thermometer range')
            values = -1000 + np.zeros(len(R))

        units = 'C'

        return values, units


# LabJack agent class
class LabJackAgent:
    def __init__(self, agent, ip_address, active_channels, function_file,
                 sampling_frequency, enable_filter=False, lowpass_order=5,
                 lowpass_cutoff=200., downsample_factor=1):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.module = None
        self.ljf = LabJackFunctions()
        self.sampling_frequency = sampling_frequency

        # Filtering params
        self.enable_filter = enable_filter
        self.lowpass_order = lowpass_order
        self.lowpass_cutoff = lowpass_cutoff
        self.downsample_factor = downsample_factor

        # Labjack channels to read
        if active_channels == 'T7-all':
            self.chs = ['AIN{}'.format(i) for i in range(14)]
        elif active_channels == 'T4-all':
            self.chs = ['AIN{}'.format(i) for i in range(12)]
        else:
            self.chs = active_channels

        # Load dictionary of unit conversion functions from yaml file. Assumes
        # the file is in the $OCS_CONFIG_DIR directory
        if function_file == 'None':
            self.functions = {}
        else:
            function_file_path = os.path.join(os.environ['OCS_CONFIG_DIR'],
                                              function_file)
            with open(function_file_path, 'r') as stream:
                self.functions = yaml.safe_load(stream)
                if self.functions is None:
                    self.functions = {}
                self.log.info(f"Applying conversion functions: {self.functions}")

        self.initialized = False
        self.take_data = False

        # Register main feed. Exclude influx due to potentially high scan rate
        agg_params = {
            'frame_length': 60,
            'exclude_influx': True
        }
        self.agent.register_feed('sensors',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        # Register downsampled feed for influx.
        agg_params_downsampled = {
            'frame_length': 60
        }
        self.agent.register_feed('sensors_downsampled',
                                 record=True,
                                 agg_params=agg_params_downsampled,
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
            # Connect with the labjack
            self.handle = ljm.openS("ANY", "ANY", self.ip_address)
            info = ljm.getHandleInfo(self.handle)
            self.log.info("\nOpened LabJack of type: %i, Connection type: %i,\n"
                          "Serial number: %i, IP address: %s, Port: %i" %
                          (info[0], info[1], info[2],
                           ljm.numberToIP(info[3]), info[4]))

        session.add_message("Labjack initialized")

        self.initialized = True

        # Start data acquisition if requested in site-config
        auto_acquire = params.get('auto_acquire', False)
        if auto_acquire:
            self.agent.start('acq')

        return True, 'LabJack module initialized.'

    def start_acq(self, session, params=None):
        """
        Task to start data acquisition. All parameters will default to those
        in site-config entry if specified. If unspecified, will default to
        the vaules below.

        Args:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz
            enable_filter (bool):
                Whether to enable the lowpass filter. Defaults to False.
            lowpass_order (int):
                Order of butterworth lowpasss filter. Defaults to 5
            lowpass_cutoff (float):
                Cutoff frequency for lowpass filter. Defaults to 200 Hz.
            downsample_factor (int):
                Factor to downsample data. Defaults to 1 (not downsampled).
        """
        if params is None:
            params = {}

        # Setup streaming parameters. Data is collected and published in
        # blocks at 1 Hz or the scan rate, whichever is less.
        scan_rate_input = params.get('sampling_frequency',
                                     self.sampling_frequency)
        scans_per_read = max(1, int(scan_rate_input))
        num_chs = len(self.chs)
        ch_addrs = ljm.namesToAddresses(num_chs, self.chs)[0]

        ### Filter stuff if specified
        enable_filter = params.get('enable_filter', self.enable_filter)
        lowpass_order = params.get('lowpass_order', self.lowpass_order)
        lowpass_cutoff = params.get('lowpass_cutoff', self.lowpass_cutoff)
        downsample_factor = params.get('downsample_factor',
                                       self.downsample_factor)
        downsample_mask = np.zeros(scans_per_read)
        lowpass_filter = FIRFilter.butter_lowpass(
            lowpass_cutoff, scan_rate_input, order=lowpass_order,
            nchans=num_chs)

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')
            self.take_data = True

            # Start the data stream. Use the scan rate returned by the stream,
            # which should be the same as the input scan rate.
            try:
                scan_rate = ljm.eStreamStart(self.handle, scans_per_read, num_chs,
                                             ch_addrs, scan_rate_input)
            except LJMError as e:  # in case the stream is running
                self.log.error(e)
                self.log.error("Stopping previous stream and starting new one")
                ljm.eStreamStop(self.handle)
                scan_rate = ljm.eStreamStart(self.handle, scans_per_read, num_chs,
                                             ch_addrs, scan_rate_input)
            self.log.info(f"\nStream started with a scan rate of {scan_rate} Hz.")

            t0 = time.time()
            read_period = scans_per_read / scan_rate

            while self.take_data:
                data = {
                    'block_name': 'sens',
                    'data': {}
                }

                # Query the labjack
                raw_output = ljm.eStreamRead(self.handle)
                # Data comes in form ['AIN0_1', 'AIN1_1', 'AIN0_2', ...]
                output = raw_output[0]
                output.reshape((num_chs, scans_per_read))
                if enable_filter:
                    lowpass_filter.lfilt(output, in_place=True)

                downsample_mask[:] = 0
                downsample_mask[::downsample_factor] = 1

                for i, ch in enumerate(self.chs):
                    ch_output = output[i, downsample_mask]
                    data['data'][ch + 'V'] = ch_output

                    # Apply unit conversion function for this channel
                    if ch in self.functions.keys():
                        new_ch_output, units = \
                            self.ljf.unit_conversion(np.array(ch_output),
                                                     self.functions[ch])
                        data['data'][ch + units] = list(new_ch_output)

                # The labjack outputs at exactly the scan rate but doesn't
                # generate timestamps. So create them here.
                t1 = t0 + read_period
                timestamps = np.linspace(t0, t1, scans_per_read)
                data['timestamps'] = timestamps[downsample_mask]
                t0 = t1

                self.agent.publish_to_feed('sensors', data)

                # Publish to the downsampled data feed only the first
                # timestamp and data point for each channel.
                data_downsampled = {
                    'block_name': 'sens',
                    'data': {},
                    'timestamp': timestamps[0]
                }
                for key, value in data['data'].items():
                    data_downsampled['data'][key] = value[0]
                self.agent.publish_to_feed('sensors_downsampled', data_downsampled)
                session.data = data_downsampled

            # Flush buffer and stop the data stream
            self.agent.feeds['sensors'].flush_buffer()
            self.agent.feeds['sensors_downsampled'].flush_buffer()
            ljm.eStreamStop(self.handle)
            self.log.info("Data stream stopped")

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')

    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--active-channels',
                        default='T7-all')
    pgroup.add_argument('--function-file', default='None')
    pgroup.add_argument('--sampling-frequency', default=2.5, type=float)
    pgroup.add_argument('--enable-filter', action='store_true',
                        help="If true, will lowpass filter data")
    pgroup.add_argument('--lowpass-order', type=int, default=5,
                        help="Order of butterworth lowpass filter")
    pgroup.add_argument('--lowpass-cutoff', type=float, default=200.,
                        help="Cutoff frequency of lowpass filter")
    pgroup.add_argument('--downsample-factor', type=int, default=1,
                        help="Factor by which to downsample data")

    return parser


if __name__ == '__main__':
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))
    parser = make_parser()
    args = site_config.parse_args(agent_class='LabJackAgent', parser=parser)

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}

    ip_address = str(args.ip_address)
    active_channels = args.active_channels
    function_file = str(args.function_file)
    sampling_frequency = args.sampling_frequency

    agent, runner = ocs_agent.init_site_agent(args)

    sensors = LabJackAgent(
        agent, ip_address=ip_address, active_channels=active_channels,
        function_file=function_file, sampling_frequency=sampling_frequency,
        enable_filter=args.enable_filter, lowpass_order=args.lowpass_order,
        lowpass_cutoff=args.lowpass_cutoff,
        downsample_factor=args.downsample_factor)

    agent.register_task('init_labjack',
                        sensors.init_labjack_task,
                        startup=init_params)
    agent.register_process('acq', sensors.start_acq, sensors.stop_acq)

    runner.run(agent, auto_reconnect=True)
