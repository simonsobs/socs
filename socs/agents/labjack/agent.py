import argparse
import csv
import os
import struct
import time

import numexpr
import numpy as np
import txaio
import yaml
from labjack import ljm
from labjack.ljm.ljm import LJMError
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from scipy.interpolate import interp1d

txaio.use_twisted()


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
            v_array (np.array):
                The voltages to be converted.
            function_info (dict):
                Specifies the type of function. If custom, also gives the function.
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
        value = 1.3332 * 10**(2 * v_array - 11)
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
        R = (2.5 - v_array) * 10000 / v_array

        # Import the Ohms to Celsius cal curve and apply cubic
        # interpolation to find the temperature
        cal_curves = os.path.join(os.path.dirname(__file__),
                                  'cal_curves/GA10K4D25_cal_curve.txt')
        reader = csv.reader(open(cal_curves),
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


class LabJackAgent:
    """Agent to collect data from LabJack device.

    Parameters:
        agent (OCSAgent): OCSAgent object for the Agent.
        ip_address (str): IP Address for the LabJack device.
        active_channels (str or list): Active channel description, i.e.
            'T7-all', 'T4-all', or list of channels in form ['AIN0', 'AIN1'].
        function_file (str): Path to file for unit conversion.
        sampling_frequency (float): Sampling rate in Hz.

    """

    def __init__(self, agent, ip_address, active_channels, function_file,
                 sampling_frequency):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.module = None
        self.ljf = LabJackFunctions()
        self.sampling_frequency = sampling_frequency

        # Labjack channels to read
        if active_channels[0] == 'T7-all':
            self.chs = ['AIN{}'.format(i) for i in range(14)]
        elif active_channels[0] == 'T4-all':
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
        self.agent.register_feed('registers',
                                 record=True,
                                 agg_params={'frame_length': 10 * 60},
                                 buffer_time=1.)

    # Task functions
    def init_labjack(self, session, params=None):
        """init_labjack(auto_acquire=False)

        **Task** - Initialize LabJack module.

        Parameters:
            auto_acquire (bool): Automatically start acq process after
                initialization. Defaults to False.

        """
        if self.initialized:
            return True, "Already initialized module"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

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
        auto_acquire_reg = params.get('auto_acquire_reg', False)

        if auto_acquire:
            self.agent.start('acq')
        if auto_acquire_reg:
            self.agent.start('acq_reg')
        return True, 'LabJack module initialized.'

    def acq(self, session, params=None):
        """acq(sampling_freq=2.5)

        **Process** - Acquire data from the Labjack.

        Parameters:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz.

        Notes:
            An example of the session data is shown below. The keys in the
            'data' dictionary correspond with configured channels from the
            ``active_channels`` attribute::

                >>> response.session['data']
                {
                  "block_name": "sens",
                  "data": {
                    "AIN0V": 0.0015984050696715713,
                    "FIO0V": 1,
                    "FIO1V": 1,
                    "AIN55V": 0.00033546771737746894,
                    "AIN116V": 0.000019733395674847998,
                  },
                  "timestamp": 1698439453.8471205
                }

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

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

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

            cur_time = time.time()
            while self.take_data:
                data = {
                    'block_name': 'sens',
                    'data': {}
                }

                # Query the labjack
                raw_output = ljm.eStreamRead(self.handle)
                output = raw_output[0]

                # Data comes in form ['AIN0_1', 'AIN1_1', 'AIN0_2', ...]
                for i, ch in enumerate(self.chs):
                    ch_output = output[i::num_chs]
                    data['data'][ch + 'V'] = ch_output

                    # Apply unit conversion function for this channel
                    if ch in self.functions.keys():
                        new_ch_output, units = \
                            self.ljf.unit_conversion(np.array(ch_output),
                                                     self.functions[ch])
                        data['data'][ch + units] = list(new_ch_output)

                # The labjack outputs at exactly the scan rate but doesn't
                # generate timestamps. So create them here.
                timestamps = [cur_time + i / scan_rate for i in range(scans_per_read)]
                cur_time += scans_per_read / scan_rate
                data['timestamps'] = timestamps

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

    def _stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    def acq_reg(self, session, params=None):
        """acq_reg(sampling_frequency=2.5)

        **Task** - Start data acquisition when you want to read out
        non-standard registers.

        In particular the custom registers labjack was built for reading out
        thermocouples. Maximum is about 2.5 Hz but is set by the register read
        time which is estimated at the beginning of the acq_reg setup step.

        Args:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz
                Maximum set by the register read time. Will reset to lower
                rate if faster than possible read time.
        """
        if params is None:
            params = {}
        # Determine the read time latency to set the max allowable
        # sampling rate by reading the register 100 times in a row
        # and recording the time it takes to read each time. Then
        # setting the max sample rate to be 50mS greater than the median
        # of the time it took to read.
        num_chs = len(self.chs)
        times = []
        for i in range(100):
            times.append(time.time())
            ljm.eReadNames(self.handle, num_chs, self.chs)[0]
        read_dt = np.round(np.median(np.diff(times)), 2) + 0.05
        max_fsamp = min(2.5, 1 / read_dt)
        # Setup streaming parameters. Data is collected and published in
        # blocks at 1 Hz or the scan rate, whichever is less.
        scan_rate_input = params.get('sampling_frequency',
                                     self.sampling_frequency)
        # Warn user that they input too fast of a sample rate and set
        # to maximum allowable.
        if scan_rate_input > max_fsamp:
            self.log.warn(f'Sampling rate {scan_rate_input} exceeds'
                          'allowable range for register read mode'
                          'if you want to sample faster please use'
                          'standard acquire mode and do not read out '
                          'any non-standard channels. Setting sampling'
                          f'rate to maximum = {max_fsamp} Hz')
            scan_rate_input = max_fsamp
            scan_rate_dt = 0
        else:
            scan_rate_dt = (1 / scan_rate_input) - read_dt

        with self.lock.acquire_timeout(0, job='acq_reg') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.take_data = True

            while self.take_data:
                data = {
                    'block_name': 'reg',
                    'data': {}
                }

                # Get a timestamp
                timestamp = time.time()
                # Query the labjack
                output = ljm.eReadNames(self.handle, num_chs, self.chs)

                # Data comes in form ['reg1', 'reg2', 'reg3', ...]
                # where regn are the registers in your active_channels
                # list in your site config file.
                for i, ch in enumerate(self.chs):
                    ch_output = output[i]
                    data['data'][ch] = ch_output

                    # Apply unit conversion function for this channel
                    if ch in self.functions.keys():
                        new_ch_output, units = \
                            self.ljf.unit_conversion(ch_output,
                                                     self.functions[ch])
                        data['data'][ch + units] = new_ch_output

                data['timestamp'] = timestamp
                self.agent.publish_to_feed('registers', data)
                time.sleep(scan_rate_dt)

            # Flush buffer and stop the data stream
            self.agent.feeds['registers'].flush_buffer()
            ljm.close(self.handle)
            self.log.info("Data stream stopped")
        return True, 'Acquisition exited cleanly.'


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')

    ip_txt = 'ip-address of LabJack'
    pgroup.add_argument('--ip-address', help=ip_txt)
    achan_txt = 'Channels or register names to readout default is to read out all '
    achan_txt += 'available outputs. But typically you would want to pass a list of '
    achan_txt += 'analog inputs (i.e. ["AIN0", "AIN1", "AIN2"]) or a list of custom '
    achan_txt += 'registers if using ``--mode=acq_reg``.'
    pgroup.add_argument('--active-channels',
                        default=['T7-all'], nargs='+', help=achan_txt)
    ffile_txt = 'Path to file that defines functions for converting analog inputs to '
    ffile_txt += 'useful units (i.e. temp, pressure, etc.)'
    pgroup.add_argument('--function-file', default='None', help=ffile_txt)
    fs_txt = 'This is the rate each channel in the `active-channels` list is sampled '
    fs_txt += 'at. In ``--mode=acq_reg`` the maximum for this is 2.5 Hz can sample much '
    fs_txt += 'faster O(kHz) in ``--mode=acq``.'
    pgroup.add_argument('--sampling-frequency', default='2.5', help=fs_txt)
    acq_txt = 'Options are **acq**: read out analog inputs (can stream quickly)'
    acq_txt += ', **acq_reg**: read out custom configured registers'
    acq_txt += ', or **idle**: leave device idle at startup.'
    pgroup.add_argument('--mode', default='acq',
                        choices=['idel', 'acq', 'acq_reg'], help=acq_txt)

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='LabJackAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}
    if args.mode == 'acq_reg':
        init_params = {'auto_acquire_reg': True}

    ip_address = str(args.ip_address)
    active_channels = args.active_channels
    function_file = str(args.function_file)
    sampling_frequency = float(args.sampling_frequency)

    agent, runner = ocs_agent.init_site_agent(args)

    sensors = LabJackAgent(agent,
                           ip_address=ip_address,
                           active_channels=active_channels,
                           function_file=function_file,
                           sampling_frequency=sampling_frequency)

    agent.register_task('init_labjack',
                        sensors.init_labjack,
                        startup=init_params)
    agent.register_process('acq', sensors.acq, sensors._stop_acq)
    agent.register_process('acq_reg', sensors.acq_reg,
                           sensors._stop_acq)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
