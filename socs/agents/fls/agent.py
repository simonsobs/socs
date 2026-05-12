import argparse
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.fls.drivers import DLCSmart

MAX_FREQ = 880.
MIN_FREQ = 20.


def _within(val, target, tolerance=1e-2):
    return abs(val - target) <= tolerance


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
        self.integration_time = None

        agg_params = {'frame_length': 60}

        self.agent.register_feed('sampling_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', type=bool, default=False)
    def initialize(self, session, params=None):
        """
        initialize(auto_acquire=False)

        ***Task*** - Initialize the connection to the DLC Smart

        Parameters:
            auto_acquire (bool): If True, start acquisition immediately after
                initialization. Default value is False.
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
                self.dlcsmart.drain_buffer()
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
            except ValueError as e:
                self.log.warn(f'Could not convert {actual_freq} to float: {e}')
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
            except ValueError as e:
                self.log.warn(f'Could not interpret scan minimum frequency: {e}')
                self.scan_min_freq = scan_min_freq

            scan_max_freq = scan_params[2]
            try:
                self.scan_max_freq = float(scan_max_freq)
            except ValueError as e:
                self.log.warn(f'Could not interpret scan maximum frequency: {e}')
                self.scan_max_freq = scan_max_freq

            scan_step = scan_params[3]
            try:
                self.scan_step = abs(float(scan_step))
                self.scan_direction = np.sign(scan_step)
            except ValueError as e:
                self.log.warn(e)
                self.scan_step = scan_step

        self.initialized = True
        print('auto_acquire:', params['auto_acquire'])

        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "FLS agent initialized"

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """
        acq(test_mode=False)

        ***Process*** - Starts the 'sampling' data acquisiton from the DLC Smart.

        Parameters:
            test mode (bool): If True, the acquisition loop breaks after one iteration.

        Notes:
            The data collected are stored in session data in the structure:

                >> response.session['data']
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
                 'integration_time': 299.3421
                 'timestamp': 1771277799.562098}
        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start sampling because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            last_time = time.time()

            self.take_data = True

            pm = Pacemaker(1 / 3, quantize=False)
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
                self.integration_time = data['integration_time']

                sampling_data = {}
                for key, val in data.items():
                    sampling_data[key] = val

                data['timestamp'] = time.time()
                session.data = data

                pub_data = {'timestamp': time.time(),
                            'block_name': 'sampling_data',
                            'data': sampling_data}

                self.agent.publish_to_feed('sampling_data', pub_data)

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

    @ocs_agent.param('state', type=str, choices=['on', 'off'])
    def toggle_laser_power(self, session, params):
        """
        toggle_laser_power(state)

        ***Task*** - Enable or disable emission from both lasers

        Parameters:
            state (str): State ('on' or 'off') to set the lasers to
        """
        state = params['state']
        with self.lock.acquire_timeout(timeout=12, job='toggle_laser_power') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            laser_status = self.lasers_on
            if laser_status:
                self.log.info('Current laser state is on.')
                on_off = 'on'
            elif laser_status is False:
                self.log.info('Current laser state is off.')
                on_off = 'off'
            if on_off == state:
                return True, f"Laser is already {state}"

            bias_amp = self.tx_bias_amp
            bias_offset = self.tx_bias_offset
            if bias_amp != 0.0 or bias_offset != 0.0:
                self.log.warn(f'Bias amplitude is {bias_amp} and bias offset '
                              f'is {bias_offset}. Setting bias to zero, then '
                              f'turning lasers {state}.')
                self.dlcsmart.set_bias_to_zero()
                time.sleep(0.3)
                bias_amp, bias_offset = self.dlcsmart.check_bias()
                if bias_amp != 0.0 or bias_offset != 0.0:
                    return False, "Bias could not be set to zero so did not toggle laser power."

            countdown = 10
            while countdown > 0:
                if session.status == "running": 
                    self.log.warn(f'Bias amplitude and bias offset are zero. Check that '
                                  f'U-shaped link is unplugged. CANCEL TASK NOW IF NOT. '
                                  f'Task will proceed in {countdown} seconds.')
                    time.sleep(1)
                    countdown -= 1
                else:
                    return False, "Laser power has not been toggled."
            self.log.info(f'Proceeding to toggle laser power {state}.')
            if state == 'on':
                self.dlcsmart.laser_emission_on()
            elif state == 'off':
                self.dlcsmart.laser_emission_off()
            time.sleep(0.3)
            laser_status = self.dlcsmart.check_laser_emission()
            if "#t" in laser_status:
                self.lasers_on = True
                return True, "Lasers turned on"
            elif "#f" in laser_status:
                self.lasers_on = False
                return True, "Lasers turned off"

    def _abort_laser_power(self, session, params):
        if session.status == "running":
            session.set_status("stopping")

    @ocs_agent.param('bias', type=str, choices=['default', 'zero'])
    def set_bias(self, session, params):
        """
        set_bias(bias)

        ***Task*** - Set the bias amplitude and offset of the lasers to a preset
                     condition.

        Parameters:
            bias (str): Preset condition to set the bias for the lasers. Options are
                        'zero' to set the bias to zero, or 'default' to set the bias to
                        default. The default bias amplitude is 1.0, and the default
                        bias offset is -0.5.
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
            time.sleep(3)
            check_bias_amp = self.tx_bias_amp
            check_bias_offset = self.tx_bias_offset
            if bias_to_set == 'zero' and (check_bias_amp, check_bias_offset) == (0., 0.):
                self.log.info('Bias successfully set to zero.')
            elif bias_to_set == 'default' and round(check_bias_amp, 1) == 1.0 and round(check_bias_offset, 1) == -0.5:
                self.log.info('Bias successfully set to default.')
            else:
                bias_amp, bias_offset = self.dlcsmart.check_bias()
                if bias_to_set == 'zero' and (bias_amp, bias_offset) == (0., 0.):
                    self.log.info('Bias successfully set to zero.')
                elif bias_to_set == 'default' and round(bias_amp, 1) == 1.0 and round(bias_offset, 1) == -0.5:
                    self.log.info('Bias successfully set to default.')
                else:
                    self.log.info(f"Bias amp is {check_bias_amp} and bias offset is {check_bias_offset}.")
                    return False, "Bias not successfully set."
        return True, f"Bias successfully set to {bias_to_set}."

    @ocs_agent.param('integration_time', type=float)
    def set_integration_time(self, session, params):
        """
        set_integration_time(integration_time)

        ***Task*** - Set the integration time of the laser system. Time is in
                     milliseconds.

        Parameters:
            integration_time (float): The integration time in milliseconds.

        """
        int_time = params['integration_time']
        self.dlcsmart.param_set("lockin:integration-time", int_time)
        return True, f"Set integration time to {int_time}."

    @ocs_agent.param('frequency', type=float, check=lambda x: MIN_FREQ <= x < MAX_FREQ)
    def set_frequency(self, session, params):
        """
        set_frequency(frequency)

        ***Task*** - Set the frequency of the laser system. Frequency must be
                     between 20 GHz and 880 GHz.

        Parameters:
            frequency (float): The frequency to set the laser to.
        """
        set_frequency = params['frequency']

        with self.lock.acquire_timeout(timeout=12, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Set the new frequency
            response = self.dlcsmart.set_frequency(set_frequency)
            if response == '0':
                return True, f"Frequency set to {set_frequency} in the DLC Smart."
            else:
                return False, "Frequency set command not received by the DLC Smart."


    @ocs_agent.param('min_frequency', type=float, check=lambda x: MIN_FREQ <= x < MAX_FREQ)
    @ocs_agent.param('max_frequency', type=float, check=lambda x: MIN_FREQ <= x < MAX_FREQ)
    @ocs_agent.param('start_direction', type=int, choices=[-1, 1])
    @ocs_agent.param('frequency_step', type=float, default=0.05, check=lambda x >= 0.01)
    @ocs_agent.param('int_time', type=float, default=300., check=lambda x: 0.5 < x <= 3000)
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
            int_time (float): Integration time for each step of the sweep (ms). Default
                              chooses the last set integration time.
        """

        min_freq = params['min_frequency']
        max_freq = params['max_frequency']
        start_dir = params['start_direction']
        freq_step = params['frequency_step']
        int_time = params['int_time']
        if int_time == 0.0:
            int_time = self.integration_time

        assert min_freq < max_freq, "max_freq must be greater than min_freq!"

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

            self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir, int_time)
            time.sleep(0.1)
            csp = self.dlcsmart.check_scan_params()
            fast_check = csp[0]
            if "#f" in fast_check:
                self.log.warn("Scan is not in fast mode. Attempting to set to fast mode.")
                self.dlcsmart.param_set("frequency:scan-mode-fast", "#t")
                time.sleep(0.1)
                csp2 = self.dlcsmart.check_scan_params()
                fast_check_2 = csp2[0]
                if "#f" in fast_check_2:
                    self.log.warn("Scan is not in fast mode on attempt 2, so scan cannot be "
                                  "commanded via the Agent. Please set scan mode to fast in "
                                  "the GUI.")
                    return False, "Could not start a scan because scan mode could not be set to fast."
            min_freq_check = csp[1]
            max_freq_check = csp[2]
            freq_step_check = abs(csp[3])
            start_dir_check = np.sign(csp[3])
            int_time_check = csp[4]
            if min_freq_check != min_freq:
                self.log.warn(f"Minimum frequency set to {min_freq_check}, not {min_freq}.")
            if max_freq_check != max_freq:
                self.log.warn(f"Maximum frequency set to {max_freq_check}, not {max_freq}.")
            if freq_step_check != freq_step:
                self.log.warn(f"Frequency step size set to {freq_step_check}, not {freq_step}.")
            if start_dir_check != start_dir:
                self.log.warn(f"Start direction set to {start_dir_check}, not {start_dir}.")
            if not _within(int_time_check, int_time, tolerance=1e-1):
                self.log.warn(f"Integration time set to {int_time_check}, not {int_time}.")

            self.dlcsmart.start_scan()
            return True, f"Started scan from {min_freq} GHz to {max_freq} GHz with step size {freq_step} and direction {start_dir}."

    @ocs_agent.param("_")
    def stop_frequency_sweep(self, agent, params):
        """
        stop_frequency_sweep()

        ***Task*** - Send a stop command to the DLC Smart to stop running a frequency
                     sweep. This command may be run during or at the end of a sweep.

        """
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
    agent.register_task('toggle_laser_power', fls_agent.toggle_laser_power,
                        aborter=fls_agent._abort_laser_power)
    agent.register_task('set_bias', fls_agent.set_bias)
    agent.register_task('set_integration_time', fls_agent.set_integration_time)
    agent.register_task('set_frequency', fls_agent.set_frequency)
    agent.register_task('run_frequency_sweeps', fls_agent.run_frequency_sweeps)
    agent.register_task('stop_frequency_sweep', fls_agent.stop_frequency_sweep)
    agent.register_process('acq', fls_agent.acq, fls_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
