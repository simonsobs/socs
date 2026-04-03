import socket
import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.fls.drivers import DLCSmart

# TODO: put these in a .yaml file
BYTE_END = "\n>"
MAX_FREQ = 880.
MIN_FREQ = 20.

def _within(val, target, tolerance=1e-2):
    return abs(val-target) <= tolerance


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
        self.lasers_on = False
        self.tx_bias_amp = None
        self.tx_bias_offset = None

        self.set_freq = None
        self.actual_freq = None

        agg_params = {'frame_length': 60} # is this correct?

        self.agent.register_feed('sampling_data',
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

#            self.dlcsmart = DLCSmart(ip_addr=self.ip, port=self.port)

            try:
                self.dlcsmart = DLCSmart(ip_addr=self.ip, port=self.port)
                welcome = self.dlcsmart.drain_buffer()
                print('welcome='+str(welcome))
            except ConnectionError:
                self.log.error("could not establish connection to DLC Smart")
                return False, "FLS agent initialization failed"

            bias_read = self.dlcsmart.check_bias()
            self.tx_bias_amp = bias_read[0]
            self.tx_bias_offset = bias_read[1]
            self.log.info(f'Tx bias amplitude: {self.tx_bias_amp}')
            self.log.info(f'Tx bias offset:  + {self.tx_bias_offset}')

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

            actual_freq = self.dlcsmart.get_actual_frequency()
            try:
                self.actual_freq = float(actual_freq)
            except ValueError:
                self.log.warn(f'Could not convert {actual_freq} to float!')
                self.actual_freq = actual_freq
            self.log.info(f'Actual frequency: {actual_freq}')

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
                     'timestamp': 1771277799.562098}
        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start sampling because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            last_time = time.time()

            self.take_sampling = True

            pm = Pacemaker(1/3, quantize=False) # what is this?
            while self.take_sampling:
                pm.sleep()
                if time.time() - last_time > 1:
                    last_time = time.time()
                if not self.lock.release_and_acquire(timeout=5):
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

                sampling_data = {}
                for key, val in data.items():
                    sampling_data[key] = val

                session.data = {"sampling_data": sampling_data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'sampling_data',
                            'data': sampling_data}

                self.agent.publish_to_feed('sampling_data', pub_data)

                if params['test_mode']:
                    break

        self.agent.feeds['fls_sampling'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """
        Stops sampling process.
        """
        if self.take_sampling:
            self.take_sampling = False
            return True, 'requested to stop taking sampling data.'
        else:
            return False, 'acq is not currently running.'

    @ocs_agent.param('state', type=str, choices=['on','off'])
    def toggle_laser_power(self, session, params):
        """
        turn_lasers_on()

        ***Task*** - Enable emission from both lasers
        """
        state = params['state']
        with self.lock.acquire_timeout(timeout=12, job='toggle_laser_power') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
        
            laser_status = self.dlcsmart.check_laser_emission()
            if "#t" in laser_status:
                self.log.info('Current laser state is on.')
                on_off = 'on'
            elif "#f" in laser_status:
                self.log.info('Current laser state is off.')
                on_off = 'off'
            if on_off == state:
                return True, f"Laser is already {state}"

            bias_amp, bias_offset = self.dlcsmart.check_bias()
            if bias_amp != 0.0 or bias_offset != 0.0:
                self.log.warn(f'Bias amplitude is {bias_amp} and bias offset '
                              f'is {bias_offset}. Setting bias to zero, then '
                              f'turning lasers {state}.')
                self.dlcsmart.set_bias_to_zero()
                time.sleep(0.01)
                bias_amp, bias_offset = self.dlcsmart.check_bias()
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
            time.sleep(0.01)
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
            time.sleep(0.01)
            check_bias_amp, check_bias_offset = self.dlcsmart.check_bias()
            if bias_to_set == 'zero' and (check_bias_amp, check_bias_offset) == (0., 0.):
                self.log.info('Bias successfully set to zero.')
            elif bias_to_set == 'default' and round(check_bias_amp, 1) == 1.0 and round(check_bias_offset, 1) == -0.5:
                self.log.info('Bias successfully set to default.')
            else:
                self.log.info("Bias not successfully set.")
                return False, "Bias not successfully set."
        return True, f"Bias successfully set to {bias_to_set}."

    @ocs_agent.param('frequency', type=float)
    def set_frequency(self, session, params):
        """
        set_frequency(frequency)

        ***Task*** - Set the frequency of the laser system, and wait until the system
                     reaches that frequency. Frequency must be between 20 GHz and
                     880 GHz.

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

            # Check to see when the actual frequency gets 'close enough' to the set frequency
#            while round(actual_frequency) != round(set_frequency):
            while not _within(actual_frequency, set_frequency):
                time.sleep(1)
#                actual_frequency = self.dlcsmart.get_actual_frequency()
                actual_frequency = self.actual_freq
                self.log.info(f"Frequency is {round(actual_frequency, 2)} GHz")
            if _within(actual_frequency, set_frequency):
                time.sleep(2)
                actual_frequency = self.actual_freq
#                actual_frequency = self.dlcsmart.get_actual_frequency()
                self.log.info(f"Frequency is {round(actual_frequency, 2)} GHz")
#                while actual_frequency < (set_frequency - precision) or actual_frequency > (set_frequency + precision):
                while not _within(actual_frequency, set_frequency):
                    time.sleep(1)
#                    actual_frequency = self.dlcsmart.get_actual_frequency()
                    actual_frequency = self.actual_freq
                    self.log.info(f"Frequency is {round(actual_frequency, 2)}, GHz")

        return True, f"Set frequency to {set_frequency} GHz"

    def _check_scan_params(self, min_freq, max_freq, freq_step, start_dir):
        """
        Check that the scan parameters are the same as what you set them to.
        """
        scan_param_check = self.dlcsmart.check_scan_params()
        if scan_param_check[0] == "#t" + BYTE_END:
            self.log.info("Scan mode set to fast")
        elif scan_param_check[0] == "#f" + BYTE_END:
            self.log.info("Scan mode set to precise")
            return False, "Scan mode must be set to fast"

            if scan_param_check[1] == min_freq and scan_param_check[2] == max_freq \
            and scan_param_check[3] == start_dir * freq_step:
                self.log.info(f"Scan parameters set: {min_freq} GHz to {max_freq} GHz " \
                              f"with step size {start_dir * freq_step}")
            else:
                if scan_param_check[1] != min_freq:
                    self.log.warn(f"Minimum frequency set to {scan_param_check[1]}, not {min_freq}")
                if scan_param_check[2] != max_freq:
                    self.log.warn(f"Maximum frequency set to {scan_param_check[2]}, not {max_freq}")
                if scan_param_check[3] != start_dir * freq_step:
                    if abs(scan_param_check[3]) != freq_step:
                        self.log.warn(f"Frequency step set to {abs(scan_param_check[3])}, not {freq_step}")
                    if np.sign(scan_param_check[3]) != start_dir:
                        self.log.warn(f"Scan direction is incorrect")
                return False, "Could not correctly set scan parameters"
        return True

    @ocs_agent.param('min_frequency', type=float)
    @ocs_agent.param('max_frequency', type=float)
    @ocs_agent.param('start_direction', type=int)
    @ocs_agent.param('frequency_step', type=float, default=0.05)
    @ocs_agent.param('num_of_sweeps', type=int, default=1)
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
        nsweeps = params['num_of_sweeps']

        assert min_freq < max_freq, "max_freq must be greater than min_freq!"
        assert min_freq >= MIN_FREQ, f"min_freq must be at least {MIN_FREQ} GHz."
        assert min_freq < MAX_FREQ, f"min_freq must be less than {MAX_FREQ} GHz."
        assert max_freq >= MIN_FREQ, f"max_freq must be at least {MIN_FREQ} GHz."
        assert max_freq < MAX_FREQ, f"max_freq must be less than {MAX_FREQ} GHz."
        assert freq_step >= 0.01, "minimum step size is 0.01 GHz."
        assert start_dir in (-1, 1), "Choose start_dir=1 (increasing) or -1 (decreasing)"
 
        scan_precision = freq_step

        with self.lock.acquire_timeout(timeout=12, job='run_frequency_sweeps') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

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

            i = 0
            while i < nsweeps:
                self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir)
                time.sleep(0.01)
                csp = self._check_scan_params(min_freq, max_freq, freq_step, start_dir)
                if not csp:
                    return False, "Could not correctly set scan params"
                self.dlcsmart.start_scan()
                time.sleep(1)
#                act_freq = self.dlcsmart.get_actual_frequency()
                act_freq = self.actual_freq

                while _within(act_freq, min_freq) or _within(act_freq, max_freq):
                    print(f'Frequency is still {act_freq}')
                    time.sleep(1)
                    act_freq = self.actual_freq
                self.log.info('Scan has started.')

                while not _within(act_freq, min_freq+scan_precision) or not _within(act_freq, max_freq-scan_precision):
                    time.sleep(1)
                    act_freq = self.actual_freq

                self.dlcsmart.stop_scan()
                self.log.info('Completed scan iteration number {i}.')
                time.sleep(1)
                start_dir = -1 * start_dir
                i += 1
            self.log.info("Frequency sweeps completed")
            return True, f"Completed {i} frequency sweeps"


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
#    agent.register_task('turn_lasers_off', fls_agent.turn_lasers_off)
    agent.register_task('set_bias', fls_agent.set_bias)
    agent.register_task('set_frequency', fls_agent.set_frequency)
    agent.register_task('run_frequency_sweeps', fls_agent.run_frequency_sweeps)
    agent.register_process('acq', fls_agent.acq, fls_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)

if __name__== '__main__':
    main()
