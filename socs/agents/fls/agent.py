import socket
import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.fls.drivers import DLCSmart

BYTE_END = "\n>"
MAX_FREQ = 880.
MIN_FREQ = 20.


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

        self.connected = False
        self.take_data = False
        self.lasers_on = False
        self.tx_bias_amp = None
        self.tx_bias_offset = None

        agg_params = {'frame_length': 60} # is this correct?

        self.agent.register_feed('scan_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        self.agent.register_feed('sampling_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        
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

            self.dlcsmart = DLCSmart(ip_addr=self.ip, command_port=self.port)

            try:
                self.dlcsmart.connect()
            except ConnectionError:
                self.log.error("could not establish connection to DLC Smart")
                return False, "FLS agent initialization failed"

            bias_read = self.dlcsmart.check_bias()
            self.tx_bias_amp = bias_read[0]
            self.tx_bias_offset = bias_read[1]

            lasers_on = self.dlcsmart.check_laser_emission()
            if lasers_on == "#t" + BYTE_END:
                self.lasers_on = True
            elif lasers_on == "#f" + BYTE_END:
                self.lasers_on = False
            else:
                self.log.warn("Could not determine if lasers are on!")

        self.connected = True

        return True, "FLS agent initialized"

    def sampling(self, session, params):
        """
        sampling()

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
        with self.lock.acquire_timeout(0, job='sampling') as acquired:
            if not acquired:
                self.log.warn(f"Could not start sampling because {self.lock.job}"
                              "is already running")
                return False, "Could not acquire lock."

            last_time = time.time()

            self.take_sampling = True

            pm = Pacemaker(1/3, quanitze=False) # what is this?
            while self.take_sampling:
                pm.sleep()
                if time.time() - last_time > 1:
                last_time = time.time()
                if not self.lock.release_and_acquire(timeout=5):
                    self.log.warn(f"Failed to re-acquire sampling lock, "
                                  "currently held by {self.lock.job}.")
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

                sampling_data = {}
                for key, val in data.items():
                    sampling_data[key] = val

                session.data = {"sampling_data": sampling_data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'sampling_data',
                            'data': sampling_data}

                self.agent.publish_to_feed('sampling_data', pub_data)

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

    def turn_lasers_on(self, session, params):
        """
        turn_lasers_on()

        ***Task*** - Enable emission from both lasers
        """
        with self.lock.acquire_timeout(timeout=5, job='turn_lasers_on') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
        
            laser_status = self.dlcsmart.check_laser_emission()
            if laser_status == "#t" + BYTE_END:
                self.lasers_on = True
            elif laser_status == "#f" + BYTE_END:
                self.lasers_on = False
            if self.lasers_on == True:
                return True, "Lasers already on"
            else:
                turn_on = self.dlcsmart.laser_emission_on()
                time.sleep(0.01)
                laser_status = self.dlcsmart.check_laser_emission()
                if laser_status == "#t" + BYTE_END:
                    self.lasers_on = True
                    return True, "Lasers turned on"
                elif laser_status == "#f" + BYTE_END:
                    self.lasers_on = False
                    return False, "Lasers did not turn on"

    def turn_lasers_off(self, session, params):
        """
        turn_lasers_off()

        ***Task*** - Disable emission from both lasers
        """
        with self.lock.acquire_timeout(timeout=5, job='turn_lasers_off') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            laser_status = self.dlcsmart.check_laser_emission()
            if laser_status == "#t" + BYTE_END:
                self.lasers_on = True
            elif laser_status == "#f" + BYTE_END:
                self.lasers_on = False
            if self.lasers_on == False:
                return True, "Lasers already off"
            else:
                turn_off = self.dlcsmart.laser_emission_off()
                time.sleep(0.01)
                laser_status = self.dlcsmart.check_laser_emission()
                if laser_status == "#t" + BYTE_END:
                    self.lasers_on = True
                    return False, "Lasers did not turn off!"
                elif laser_status == "#f" + BYTE_END:
                    self.lasers_on = False
                    return True, "Lasers are off"
    
    @ocs_agent.param('bias', type=str)
    def set_bias(self, sesssion, params):
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
        with self.lock.acquire_timeout(timeout=5, job='turn_lasers_off') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"
            if bias_to_set == 'zero':
                self.dlcsmart.set_bias_to_zero()
            elif bias_to_set == 'default':
                self.dlcsmart.set_bias_to_default()
            else:
                self.log.warn(f"{bias_to_set} is not available. Choose 'zero' or 'default'.")
                return False, f"Could not set bias to {bias_to_set}"
            time.sleep(0.01)
            check_bias = self.dlcsmart.check_bias
            if bias_to_set == 'zero' and check_bias == (0., 0.):
                self.log.info('Bias successfully set to zero.')
            elif bias_to_set == 'default' and check_bias == (1., -0.5):
                self.log.info('Bias successfully set to default.')
            else:
                self.log.info('Bias not successfully set.')
                return False, "Bias not successfully set.')
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
        assert set_frequency >= MIN_FREQ, "Frequency must be above 20 GHz!"
        assert set_frequency < MAX_FREQ, "Frequency must be below 880 GHz!"

        with self.lock.acquire_timeout(timeout=5, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Read the actual frequency
            actual_frequency = self.dlcsmart.get_actual_frequency()

            # Set the new frequency
            set_the_freq = self.dlcsmart.set_frequency(set_frequency)

            # Check to see when the actual frequency gets 'close enough' to the set frequency
            while round(actual_frequency, 2) != set_frequency:
                time.sleep(1)
                actual_frequency = self.dlcsmart.get_actual_frequency()
                self.log.info(f"Frequency is {actual_frequency} GHz")
            if round(actual_frequency, 2) == set_frequency:
                time.sleep(2)
                actual_frequency = self.dlcsmart.get_actual_frequency()
                self.log.info(f"Frequency is {actual_frequency} GHz")
                while round(actual_frequency, 2) != set_frequency:
                    time.sleep(1)
                    actual_frequency = self.dlcsmart.get_actual_frequency()
                    self.log.info(f"Frequency is {actual_frequency} GHz")

        return True, f"Set frequency to {set_frequency} GHz"

    def _check_scan_params(min_freq, max_freq, freq_step, start_dir):
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
                self.log.info(f"Scan parameters set: {min_freq} GHz to {max_freq} GHz "}
                              f"with step size {start_dir * freq_step}")
            else:
                if scan_param_check[1] != min_freq:
                    self.log.info(f"Minimum frequency set to {scan_param_check[1]}, not {min_freq}")
                if scan_param_check[2] != max_freq:
                    self.log.info(f"Maximum frequency set to {scan_param_check[2]}, not {max_freq}")
                if scan_param_check[3] != start_dir * freq_step:
                    if abs(scan_param_check[3]) != freq_step:
                        self.log.info(f"Frequency step set to {abs(scan_param_check[3])}, not {freq_step})
                    if np.sign(scan_param_check[3]) != start_dir:
                        self.log.info(f"Scan direction is incorrect")
                return False, "Could not correctly set scan parameters"
        return True

    @ocs_agent.param('min_frequency', type=float)
    @ocs_agent.param('max_frequency', type=float)
    @ocs_agent_param('start_direction', type=int)
    @ocs_agent.param('frequency_step', type=float, default=0.05)
    @ocs_agent_param('num_of_sweeps', type=int, default=1)
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
        assert min_freq >= MIN_FREQ, "min_freq must be at least 20 GHz."
        assert min_freq < MAX_FREQ, "min_freq must be less than 880 GHz."
        assert max_freq >= MIN_FREQ, "max_freq must be at least 20 GHz."
        assert max_freq < MAX_FREQ, "max_freq must be less than 880 GHz."
        assert freq_step >= 0.01, "minimum step size is 0.01 GHz."
        assert start_dir in (-1, 1), "Choose start_dir=1 (increasing) or -1 (decreasing)"
 
        with self.lock.acquire_timeout(timeout=5, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.dlcsmart.clear_scan_data()
            self.log.info("Cleared stored scan data from the DLC Smart memory")

            i = 0
            while i < nsweeps:
                self.dlcsmart.set_scan_params(min_freq, max_freq, freq_step, start_dir)
                time.sleep(0.01)
                csp = self._check_scan_params(min_freq, max_freq, freq_step, start_dir)
                if not csp:
                    return False, "Could not correctly set scan params"
                self.dlcsmart.start_scan()
                time.sleep(1)
                scan_data = self.dlcsmart.get_scan_data()
                session.data = {"scan_data": scan_data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'scan_data',
                            'data': scan_data}

                self.agent.publish_to_feed('scan_data', pub_data)
                act_freq = self.dlcsmart.get_actual_frequency()
                while act_freq > min_freq and act_freq < max_freq:
                    time.sleep(1)
                    scan_data = self.dlcsmart.get_scan_data()
                    session.data = {"scan_data": scan_data,
                                    "timestamp": time.time()}

                    pub_data = {'timestamp': time.time(),
                                'block_name': 'scan_data',
                                'data': scan_data}

                    self.agent.publish_to_feed('scan_data', pub_data)

                    act_freq = self.dlcsmart.get_actual_frequency()
                self.dlcsmart.stop_scan()
                time.sleep(1)
                start_dir = -1 * start_dir
                i += 1
            self.log.info("Frequency sweeps completed")
            while len(scan_data['scan_point_number']):
                scan_data = self.dlcsmart.get_scan_data()
                session.data = {"scan_data": scan_data,
                                "timestamp": time.time()}

                pub_data = {'timestamp': time.time(),
                            'block_name': 'scan_data',
                            'data': scan_data}

                self.agent.publish_to_feed('scan_data', pub_data)
            self.log.info("Finished getting scan data")
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

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='FLSAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    fls_agent = FLSAgent(agent, args.ip, args.port)
    agent.register_task('initialize', fls_agent.initialize)
    agent.register_task('turn_lasers_on', fls_agent.turn_lasers_on)
    agent.register_task('turn_lasers_off', fls_agent.turn_lasers_off)
    agent.register_task('set_bias', fls_agent.set_bias)
    agent.register_task('set_frequency', fls_agent.set_frequency)
    agent.register_task('run_frequency_sweeps', fls_agent.run_frequency_sweeps)
    agent.register_process('sampling', fls_agent.sampling, fls_agent._stop_acq)
