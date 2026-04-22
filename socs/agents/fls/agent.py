import socket
import argparse
import time
import numpy as np

from autobahn.twisted.util import sleep as dsleep

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.fls.drivers import DLCSmart

# TODO: put these in a .yaml file
MAX_FREQ = 880.
MIN_FREQ = 20.

def _within(val, target, tolerance=1e-2):
    return abs(val-target) <= tolerance

def _check_scan_params(fls, min_freq, max_freq, freq_step, start_dir):
    """
    Check that the scan parameters are the same as what you set them to.
    """
    scan_mode = fls.scan_mode
    if scan_mode == 'fast':
        fls.log.info("Scan mode set to fast")
    elif scan_mode == 'precise':
        fls.log.info("Scan mode set to precise")
        return False, "Scan mode must be set to fast."

    scan_min_freq = fls.scan_min_freq
    scan_max_freq = fls.scan_max_freq
    scan_step_size = fls.scan_step
    scan_direction = fls.scan_direction

    if scan_min_freq != min_freq:
        fls.log.warn(f"Minimum frequency set to {scan_min_freq}, not {min_freq}!")
        return False, "Scan parameter validation failed: minimum frequency."
    if scan_max_freq != max_freq:
        fls.log.warn(f"Minimum frequency set to {scan_max_freq}, not {max_freq}!")
        return False, "Scan parameter validation failed: maximum frequency."
    if scan_step_size != freq_step:
        fls.log.warn(f"Scan step size set to {scan_step_size}, not {freq_step}!")
        return False, "Scan parameter validation failed: step size."
    if scan_direction != start_dir:
        fls.log.warn(f"Start direction set to {scan_direction}, not {start_dir}!")
        return False, "Scan parameter validation failed: scan direction."

    fls.log.info(f"Scan parameters set: {min_freq} GHz to {max_freq} GHz "\
                 f"with step size {start_dir * freq_step}.")

    return True


class FLSAgent:
    """
    Agent for operating the lasers in the Frequency-selectable Laser Source
    (FLS) calibrator instrument for passband measurements.

    Args:
        ip (str): IP address for the DLC Smart laser controller
        port (int, optional): TCP port for DLC Smart communication.
            Default is 1998
    """

    def __init__(self, agent, ip, port=1998):
        self.lock = TimeoutLock()
        self.agent = agent
        self.log = agent.log
        self.ip = ip
        self.port = port
        self.dlcsmart = None

        self.initialized = False
        self.take_data = False
        self.run_sweep = False

        # for internal referencing
        self.lasers_on = False
        self.tx_bias_amp = None
        self.tx_bias_offset = None
        self.set_freq = None
        self.actual_freq = None
        self.scan_mode = None
        self.scan_min_freq = None
        self.scan_max_freq = None
        self.scan_step = None
        self.scan_direction = None

        agg_params = {'frame_length': 60} # is this correct?

        self.agent.register_feed('sampling_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        self.agent.register_feed('scan_sampling_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', type=bool, default=False)
    def initialize(self, session, params=None):
        """
        initialize()

        ***Task*** - Initialize the connection to the DLC Smart
        """
        if self.initialized:
            return True, "Already initialized"
        with self.lock.acquire_timeout(0, job='initialize') as acquired:
            if not acquired:
                self.log.warn(f"Could not start initialize because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            # Make the connection and read out the welcome message
            try:
                self.dlcsmart = DLCSmart(ip_addr=self.ip, port=self.port)
                welcome = self.dlcsmart.drain_buffer()
                print('welcome='+str(welcome))
            except ConnectionError:
                self.log.error("could not establish connection to DLC Smart")
                return False, "FLS agent initialization failed"

            # Read the voltage bias and voltage offset
            bias_read = self.dlcsmart.check_bias()
            self.tx_bias_amp = bias_read[0]
            self.tx_bias_offset = bias_read[1]
            self.log.info(f'Tx bias amplitude: {self.tx_bias_amp}')
            self.log.info(f'Tx bias offset:  + {self.tx_bias_offset}')

            # Read the laser emission state (on/off)
            lasers_on = self.dlcsmart.check_laser_emission()
            if "#t" in lasers_on:
                self.lasers_on = True
                self.log.info('Lasers are on.')
            elif "#f" in lasers_on:
                self.lasers_on = False
                self.log.info('Lasers are off.')
            else:
                print(lasers_on)
                self.log.warn("Could not determine if lasers are on!")

            # Read the actual frequency
            actual_freq = self.dlcsmart.get_actual_frequency()
            try:
                self.actual_freq = float(actual_freq)
            except ValueError:
                self.log.warn(f'Could not convert {actual_freq} to float!')
                self.actual_freq = actual_freq
            self.log.info(f'Actual frequency: {actual_freq}')

            # Read the scan parameters
            scan_params = self.dlcsmart.check_scan_params()

            scan_mode = scan_params[0]
            if "#t" in scan_mode:
                self.scan_mode = 'fast'
            elif "#f" in scan_mode:
                self.scan_mode = 'precise'
            else:
                self.log.warn('Could not interpret scan mode')
                self.scan_mode = scan_mode
            
            scan_min_freq = scan_params[1]
            try:
                self.scan_min_freq = float(scan_min_freq)
            except ValueError:
                self.log.warn('Could not interpret scan minimum frequency')
                self.scan_min_freq = scan_min_freq

            scan_max_freq = scan_params[2]
            try:
                self.scan_max_freq = float(scan_max_freq)
            except ValueError:
                self.log.warn('Could not interpret scan maximum frequency')
                self.scan_max_freq = scan_max_freq

            scan_step = scan_params[3]
            try:
                self.scan_step = abs(float(scan_step))
                self.scan_direction = np.sign(scan_step)
            except ValueError as e:
                self.log.warn(e)
                self.scan_step = scan_step
                
            
        self.initialized = True

        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "FLS agent initialized"

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """
        acq()

        ***Process*** - Starts the 'sampling' data acquisiton from the DLC Smart.

        Notes:
            The data collected are stored in session data in the structure:

                >> response.session['data']
                {'fields':
                    {'set_frequency': 110.0,
                     'actual_frequency': 109.3425,
                     'photocurrent': 0.1124,
                     'bias_voltage': 0.999834227,
                     'bias_offset': -0.498235892,
                     'lasers_on': True,
                     'scan_mode': 'fast',
                     'scan_min_frequency': 120.0,
                     'scan_max_frequency': 180.0,
                     'scan_step': 0.05,
                     'scan_direction': 1,
                     'timestamp': 1771277799.562098}
        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start sampling because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            last_time = time.time()

            self.take_data = True

            pm = Pacemaker(1/3, quantize=False)
            while self.take_data:
                pm.sleep()
                if time.time() - last_time > 1:
                    last_time = time.time()
                if not self.lock.release_and_acquire(timeout=12):
                    self.log.warn(f"acq: Failed to re-acquire sampling lock, "
                                  f"currently held by {self.lock.job}.")
                    continue

                try:
                     data = self.dlcsmart.sampling()
                     if session.degraded:
                         self.log.info("Connection re-established.")
                         session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from DLC Smart. Check network connection")
                    session.degraded = True
                    time.sleep(1)
                    continue

                self.set_freq = data['set_frequency']
                self.actual_freq = data['actual_frequency']
                self.tx_bias_amp = data['bias_voltage']
                self.tx_bias_offset = data['bias_offset']
                self.scan_mode = data['scan_mode']
                self.scan_min_freq = data['scan_min_frequency']
                self.scan_max_freq = data['scan_max_frequency']
                self.scan_step = data['scan_step']
                self.scan_direction = data['scan_direction']
                self.lasers_on = data['lasers_on']

                sampling_data = {}
                for key, val in data.items():
                    sampling_data[key] = val

                session.data = {"sampling_data": sampling_data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'sampling_data',
                            'data': sampling_data}

                self.agent.publish_to_feed('sampling_data', pub_data)

                print(pub_data)

                if params['test_mode']:
                    break

        self.agent.feeds['sampling_data'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """
        Stops sampling process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking sampling data.'
        else:
            return False, 'acq is not currently running.'

    @ocs_agent.param('state', type=str, choices=['on','off'])
    def toggle_laser_power(self, session, params):
        """
        toggle_laser_power(state)

        ***Task*** - Enable or disable emission from both lasers

        Parameters
        ----------
            state (str): State ('on' or 'off') to set the lasers to
        """
        state = params['state']
        with self.lock.acquire_timeout(timeout=12, job='toggle_laser_power') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
        
#            laser_status = self.dlcsmart.check_laser_emission()
            laser_status = self.lasers_on
            if laser_status == True:
                self.log.info('Current laser state is on.')
                on_off = 'on'
            elif laser_status == False:
                self.log.info('Current laser state is off.')
                on_off = 'off'
            if on_off == state:
                return True, f"Laser is already {state}"

#            bias_amp, bias_offset = self.dlcsmart.check_bias()
            bias_amp = self.tx_bias_amp
            bias_offset = self.tx_bias_offset
            if bias_amp != 0.0 or bias_offset != 0.0:
                self.log.warn(f'Bias amplitude is {bias_amp} and bias offset '
                              f'is {bias_offset}. Setting bias to zero, then '
                              f'turning lasers {state}.')
                self.dlcsmart.set_bias_to_zero()
                time.sleep(0.3)
#                bias_amp, bias_offset = self.dlcsmart.check_bias()
                bias_amp = self.tx_bias_amp
                bias_offset = self.tx_bias_offset
                if bias_amp != 0.0 or bias_offset != 0.0:
                    return False, "Bias could not be set to zero so did not toggle laser power."


            countdown = 10
            while countdown > 0:
                self.log.warn(f'Bias amplitude and bias offset are zero. Check that U-shaped link '
                              f'is unplugged. CANCEL TASK NOW IF NOT. Task will proceed in '
                              f'{countdown} seconds.')
                time.sleep(1)
                countdown -= 1
            self.log.info(f'Proceeding to toggle laser power {state}.')
            if state == 'on':
                change_state = self.dlcsmart.laser_emission_on()
            elif state == 'off':
                change_state = self.dlcsmart.laser_emission_off()
            time.sleep(0.3)
            laser_status = self.dlcsmart.check_laser_emission()
            if "#t" in laser_status:
                self.lasers_on = True
                return True, "Lasers turned on"
            elif "#f" in laser_status:
                self.lasers_on = False
                return True, "Lasers turned off"
    
    @ocs_agent.param('bias', type=str, choices=['default', 'zero'])
    def set_bias(self, session, params):
        """
        set_bias(bias)

        ***Task*** - Set the bias amplitude and offset of the lasers to a preset
                     condition.

        Parameters:
            bias (str): Preset condition to set the bias for the lasers. Options are
                        'zero' to set the bias to zero, or 'default' to set the bias to
                        default.
        """
        bias_to_set = params['bias']
        with self.lock.acquire_timeout(timeout=12, job='set_bias') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
            if bias_to_set == 'zero':
                self.dlcsmart.set_bias_to_zero()
            elif bias_to_set == 'default':
                self.dlcsmart.set_bias_to_default()
#            yield dsleep(3)
            time.sleep(3)
#            check_bias_amp, check_bias_offset = self.dlcsmart.check_bias()
            check_bias_amp = self.tx_bias_amp
            check_bias_offset = self.tx_bias_offset
            if bias_to_set == 'zero' and (check_bias_amp, check_bias_offset) == (0., 0.):
                self.log.info('Bias successfully set to zero.')
            elif bias_to_set == 'default' and round(check_bias_amp, 1) == 1.0 and round(check_bias_offset, 1) == -0.5:
                self.log.info('Bias successfully set to default.')
            else:
#                yield dsleep(10)
                bias_amp, bias_off = self.dlcsmart.check_bias()
                self.tx_bias_amp = bias_amp
                self.tx_bias_offset = bias_off
                check_bias_amp = self.tx_bias_amp
                check_bias_offset = self.tx_bias_offset
                if bias_to_set == 'zero' and (check_bias_amp, check_bias_offset) == (0., 0.):
                    self.log.info('Bias successfully set to zero.')
                elif bias_to_set == 'default' and round(check_bias_amp, 1) == 1.0 and round(check_bias_offset, 1) == -0.5:
                    self.log.info('Bias successfully set to default.')
                else:
                    self.log.info(f"Bias amp is {check_bias_amp} and bias offset is {check_bias_offset}.")
                    return False, "Bias not successfully set."
        return True, f"Bias successfully set to {bias_to_set}."

    @ocs_agent.param('frequency', type=float)
    def set_frequency(self, session, params):
        """
        set_frequency(frequency)

        ***Task*** - Set the frequency of the laser system. Frequency must be
                     between 20 GHz and 880 GHz.

        Parameters:
            frequency (float): The frequency to set the laser to.
        """
        set_frequency = params['frequency']
#        precision = 0.01
        assert set_frequency >= MIN_FREQ, f"Frequency must be above {MIN_FREQ} GHz!"
        assert set_frequency < MAX_FREQ, f"Frequency must be below {MAX_FREQ} GHz!"

        with self.lock.acquire_timeout(timeout=12, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Read the actual frequency
#            actual_frequency = self.dlcsmart.get_actual_frequency()
            actual_frequency = self.actual_freq

            # Set the new frequency
            set_the_freq = self.dlcsmart.set_frequency(set_frequency)
            if set_the_freq == '0':
                return True, f"Frequency set to {set_frequency} in the DLC Smart."

            # Check to see when the actual frequency gets 'close enough' to the set frequency
#            while round(actual_frequency) != round(set_frequency):
#            while not _within(actual_frequency, set_frequency):
#                time.sleep(0.3)
#                actual_frequency = self.dlcsmart.get_actual_frequency()
#                self.actual_freq = actual_frequency
#                self.log.info(f"Frequency is {round(actual_frequency, 2)} GHz")
#            if _within(actual_frequency, set_frequency):
#                time.sleep(0.3)
#                actual_frequency = self.dlcsmart.get_actual_frequency()
#                self.actual_freq = actual_frequency
#                self.log.info(f"Frequency is {round(actual_frequency, 2)} GHz")
#                while actual_frequency < (set_frequency - precision) or actual_frequency > (set_frequency + precision):
#                while not _within(actual_frequency, set_frequency):
#                    time.sleep(1)
#                    actual_frequency = self.dlcsmart.get_actual_frequency()
#                    self.actual_freq = actual_frequency
#                    self.log.info(f"Frequency is {round(actual_frequency, 2)}, GHz")
#
#        return True, f"Set frequency to {set_frequency} GHz"

    @ocs_agent.param('min_frequency', type=float)
    @ocs_agent.param('max_frequency', type=float)
    @ocs_agent.param('start_direction', type=int, choices=[-1,1])
    @ocs_agent.param('frequency_step', type=float, default=0.05)
#    @ocs_agent.param('num_of_sweeps', type=int, default=1)
    def run_frequency_sweeps(self, session, params):
        """
        run_frequency_sweeps(min_frequency, max_frequency, start_direction,
                             frequency_step, num_of_sweeps)

        ***Task*** - Run frequency sweeps between the two frequency values.

        Parameters:
            min_frequency (float): Minimum frequency for the sweeps (GHz).
            max_frequency (float): Maximum frequency for the sweeps (GHz).
            start_direction (int): Indicates increasing or decreasing frequency. Use
                                   start_direction = 1 for increasing frequency, or 
                                   start_direction = -1 for decreasing frequency
            frequency_step (float): Step size between frequencies during the sweep (GHz).
                                    Must be at least 0.01 GHz.
            num_of_sweeps (int): Number of times to sweep across the frequency range.
                                 Automatically changes between increasing and decreasing
                                 frequency.
        """
        
        min_freq = params['min_frequency']
        max_freq = params['max_frequency']
        start_dir = params['start_direction']
        freq_step = params['frequency_step']
#        nsweeps = params['num_of_sweeps']

        assert min_freq < max_freq, "max_freq must be greater than min_freq!"
        assert min_freq >= MIN_FREQ, f"min_freq must be at least {MIN_FREQ} GHz."
        assert min_freq < MAX_FREQ, f"min_freq must be less than {MAX_FREQ} GHz."
        assert max_freq >= MIN_FREQ, f"max_freq must be at least {MIN_FREQ} GHz."
        assert max_freq < MAX_FREQ, f"max_freq must be less than {MAX_FREQ} GHz."
        assert freq_step >= 0.01, "minimum step size is 0.01 GHz."
        assert start_dir in (-1, 1), "Choose start_dir=1 (increasing) or -1 (decreasing)"
 
#        scan_precision = freq_step
        fls = self
#        self.take_data = False

#        with self.lock.acquire_timeout(0, job='run_frequency_sweeps') as acquired:
#            if not acquired:
#                self.log.warn(f"Could not start run_frequency_sweeps because {self.lock.job} "
#                              "is already running")
#                return False, "Could not acquire lock."

        with self.lock.acquire_timeout(timeout=12, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.log.info(f'Scan called with min frequency {min_freq}, max frequency {max_freq}, '
                          f'start direction {start_dir}, freq step {freq_step}.')

            self.dlcsmart.clear_scan_data()
            self.log.info("Cleared stored scan data from the DLC Smart memory")

            if start_dir == 1 and not _within(self.actual_freq, min_freq):
                self.log.warn('run_frequency_sweeps called with increasing frequency, '
                              'but laser is not at min_freq.')
                if min_freq != self.set_freq:
                    self.log.warn(f'Set frequency is {self.set_freq} and min_freq is {min_freq}.')

            if start_dir == -1 and not _within(self.actual_freq, max_freq):
                self.log.warn('run_frequency_sweeps called with decreasing frequency, '
                              'but laser is not at max_freq.')
                if max_freq != self.set_freq:
                    self.log.warn(f'Set frequency is {self.set_freq} and max_freq is {max_freq}.')

            self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir)
            time.sleep(0.1)
            csp = _check_scan_params(fls, min_freq, max_freq, freq_step, start_dir)
            if not csp:
                return False, "Could not correctly set scan params."
            self.dlcsmart.start_scan()
            return True, f"Started scan from {min_freq} GHz to {max_freq} GHz with step size {freq_step} and direction {start_dir}."
#            last_time = time.time()
#
#            self.take_data = True

#            pm = Pacemaker(1/5, quantize=False)
#            while self.take_data:
#            while self.run_scan:
#                scan_iter = 0.
#                pm.sleep()
#                if time.time() - last_time > 1:
#                    last_time = time.time()
##                if not self.lock.release_and_acquire(timeout=5):
##                    self.log.warn(f"run_frequency_sweeps: Failed to re-acquire sampling lock, "
##                                  f"currently held by {self.lock.job}.")
##                    continue
#                print(scan_iter, nsweeps)
#                while scan_iter < nsweeps:
#                    print(scan_iter, nsweeps)
#                    self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir)
##                    csp = _check_scan_params(fls, min_freq, max_freq, freq_step, start_dir)
##                    if not csp:
##                        return False, "Could not correctly set scan params."
#                    self.dlcsmart.start_scan()
#
#                    act_freq = self.actual_freq
#
#                    while _within(act_freq, min_freq) or _within(act_freq, max_freq):
#                        act_freq = self.actual_freq
#                        self.log.info(f"Frequency is {act_freq}, so scan has not started.")
#                        try:
#                            data = self.dlcsmart.sampling()
#                            print(data)
#                            if session.degraded:
#                                self.log.info("Connection re-established.")
#                                session.degraded = False
#                        except ConnectionError:
#                            self.log.error("Failed to get data from DLC Smart. Check network connection")
#                            session.degraded = True
#                            time.sleep(1)
#                            continue
#
#                        self.set_freq = data['set_frequency']
#                        self.actual_freq = data['actual_frequency']
#
#                        sampling_data = {}
#                        for key, val in data.items():
#                            sampling_data[key] = val
#
#                        session.data = {"scan_sampling_data": sampling_data,
#                                        "timestamp": time.time()}
#
#                        pub_data = {'timestamp': time.time(),
#                                    'block_name': 'scan_sampling_data',
#                                    'data': sampling_data}
#
#                        print(pub_data)
#
#                        self.agent.publish_to_feed('scan_sampling_data', pub_data)
#                        time.sleep(1)
#                        if not _within(act_freq, min_freq) and not _within(act_freq, max_freq):
#                            break
#
#                    while not _within(act_freq, min_freq) and not _within(act_freq, max_freq):
#                        self.log.info("Scan is still running.")
#                        try:
#                            data = self.dlcsmart.sampling()
#                            if session.degraded:
#                                self.log.info("Connection re-established.")
#                                session.degraded = False
#                        except ConnectionError:
#                            self.log.error("Failed to get data from DLC Smart. Check network connection")
#                            session.degraded = True
#                            time.sleep(1)
#                            continue
#
#                        self.set_freq = data['set_frequency']
#                        self.actual_freq = data['actual_frequency']
#
#                        print(self.set_freq, self.actual_freq, act_freq)
#                        sampling_data = {}
#                        for key, val in data.items():
#                            sampling_data[key] = val
#
#                        session.data = {"scan_sampling_data": sampling_data,
#                                        "timestamp": time.time()}
#
#                        pub_data = {'timestamp': time.time(),
#                                    'block_name': 'scan_sampling_data',
#                                    'data': sampling_data}
#
#                        self.agent.publish_to_feed('scan_sampling_data', pub_data)
#
#                        act_freq = self.actual_freq
#
#                        if _within(act_freq, min_freq) or _within(act_freq, max_freq):
#                            break
#
#                    self.log.info(f'Scan iteration number {scan_iter} completed. Waiting for scan_end call.')
#
#                    self.dlcsmart.stop_scan()
#                    self.log.info('Stop_scan called.')
#                    self.log.info(f'Completed scan iteration number {scan_iter}.')
#                    if scan_iter < nsweeps:
#                        scan_iter += 1
#                    if scan_iter < nsweeps:
#                        start_dir = -1 * start_dir
#
#                if not self.lock.release_and_acquire(timeout=12):
#                    self.log.warn(f"run_frequency_sweeps: Failed to re-acquire sampling lock, "
#                                  f"currently held by {self.lock.job}.")
#
#        self.agent.feeds['scan_sampling_data'].flush_buffer()
#        self.run_sweep = False
#        self.dlcsmart.stop_scan()
#        return True, "Frequency scan completed."
#

#        with self.lock.acquire_timeout(timeout=12, job='run_frequency_sweeps') as acquired:
#            if not acquired:
#                self.log.warn(f"Could not start Task because "
#                              f"{self.lock.job} is already running")
#                return False, "Could not acquire lock"
#
#            last_time = time.time()
#
#            self.dlcsmart.clear_scan_data()
#            self.log.info("Cleared stored scan data from the DLC Smart memory")
#
#            if start_dir == 1 and not _within(self.actual_freq, min_freq):
#                self.log.warn('run_frequency_sweeps called with increasing frequency, '
#                              'but laser is not at min_freq.')
#                if min_freq != self.set_freq:
#                    self.log.warn(f'Set frequency is {self.set_freq} and min_freq is {min_freq}.')
#
#            if start_dir == -1 and not _within(self.actual_freq, max_freq):
#                self.log.warn('run_frequency_sweeps called with decreasing frequency, '
#                              'but laser is not at max_freq.')
#                if max_freq != self.set_freq:
#                    self.log.warn(f'Set frequency is {self.set_freq} and max_freq is {max_freq}.')
#
#            pm = Pacemaker(1/3, quantize=False)
#            self.run_scan = True
#            while self.run_scan:
#                i = 0
#                while i < nsweeps:
#                    self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir)
#                    time.sleep(0.01)
#                    csp = _check_scan_params(fls, min_freq, max_freq, freq_step, start_dir)
#                    if not csp:
#                        return False, "Could not correctly set scan params"
#                    self.dlcsmart.start_scan()
#                    time.sleep(1)
#                    act_freq = self.dlcsmart.get_actual_frequency()
#                    act_freq = self.actual_freq
#
#                    while _within(act_freq, min_freq) or _within(act_freq, max_freq):
#                        print(f'Frequency is {act_freq}, so scan has not started.')
#                        time.sleep(1)
#                        act_freq = self.actual_freq
#                    self.log.info('Scan has started.')
#
#                    while not _within(act_freq, min_freq+scan_precision) and not _within(act_freq, max_freq-scan_precision):
#                        time.sleep(1)
#                        act_freq = self.actual_freq
#                        self.log.info('Scan is still running.')
#                    self.log.info(f'Scan iteration number {i} has reached the end frequency. Waiting for stop_scan.')
#
#                self.dlcsmart.stop_scan()
#                self.log.info('Completed scan iteration number {i}.')
#                time.sleep(1)
#                start_dir = -1 * start_dir
#                i += 1
#            self.log.info("Frequency sweeps completed")
#            return True, f"Completed {i} frequency sweeps"

#    def _stop_freq_sweep(self, session, params):
#        """         
#        Stops run_frequency_sweeps process.
#        """             
#        if self.run_sweep:
#            self.run_sweep = False
#            return True, 'Requested to stop running a frequency sweep.'
#        else:
#            return False, 'run_frequency_sweeps is not currently running.'

    @ocs_agent.param("_")
    def stop_frequency_sweep(self, agent, params):
        with self.lock.acquire_timeout(timeout=12, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
            self.dlcsmart.stop_scan()
        return True, "Sent stop scan to the DLC Smart."

def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documenation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip')
    pgroup.add_argument('--port', default=1998)
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='FLSAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    fls_agent = FLSAgent(agent, args.ip, args.port)
    agent.register_task('initialize', fls_agent.initialize, startup=init_params)
    agent.register_task('toggle_laser_power', fls_agent.toggle_laser_power)
    agent.register_task('set_bias', fls_agent.set_bias)
    agent.register_task('set_frequency', fls_agent.set_frequency)
    agent.register_task('run_frequency_sweeps', fls_agent.run_frequency_sweeps)
#    agent.register_process('run_frequency_sweeps', fls_agent.run_frequency_sweeps, fls_agent._stop_freq_sweep)#, blocking=False)
    agent.register_task('stop_frequency_sweep', fls_agent.stop_frequency_sweep)
    agent.register_process('acq', fls_agent.acq, fls_agent._stop_acq)#, blocking=False)

    runner.run(agent, auto_reconnect=True)

if __name__== '__main__':
    main()
