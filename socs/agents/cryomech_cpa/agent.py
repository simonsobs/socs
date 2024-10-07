# Script to log and readout PTC data through ethernet connection.
# Tamar Ervin and Jake Spisak, February 2019
# Sanah Bhimani, May 2022

import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.cryomech_cpa.drivers import PTC


class PTCAgent:
    """Agent to connect to a single cryomech compressor.

    Parameters:
        port (int): TCP port to connect to.
        ip_address (str): IP Address for the compressor.
        f_sample (float, optional): Data acquisiton rate, defaults to 2.5 Hz.
        fake_errors (bool, optional): Generates fake errors in the string
            output 50% of the time.

    """

    def __init__(self, agent, port, ip_address, f_sample=2.5,
                 fake_errors=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.fake_errors = fake_errors

        self.port = port
        self.module = None
        self.f_sample = f_sample

        self.initialized = False
        self.take_data = False

        # Registers data feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('ptc_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init(auto_acquire=False)

        **Task** - Initializes the connection to the PTC.

        Parameters:
            auto_acquire (bool): Automatically start acq process after
                initialization if True. Defaults to False.

        """
        if self.initialized:
            return True, "Already Initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            # Establish connection to ptc
            self.ptc = PTC(self.ip_address, port=self.port,
                           fake_errors=self.fake_errors)

            # Test connection and display identifying info
            try:
                self.ptc.get_data()
            except ConnectionError:
                self.log.error("Could not establish connection to compressor.")
                return False, "PTC agent initialization failed"
            print("PTC Model:", self.ptc.model)
            print("PTC Serial Number:", self.ptc.serial)
            print("Software Revision is:", self.ptc.software_revision)

        self.initialized = True

        # Start data acquisition if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "PTC agent initialized"

    @ocs_agent.param('state', type=str, choices=['off', 'on'])
    def power_ptc(self, session, params=None):
        """power_ptc(state=None)

        **Task** - Remotely turn the PTC on or off.

        Parameters
        ----------
        state : str
            Desired power state of the PTC, either 'on', or 'off'.

        """
        with self.lock.acquire_timeout(3, job='power_ptc') as acquired:
            if not acquired:
                self.log.warn("Could not start task because {} is already "
                              "running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.ptc.power(params['state'])

        return True, "PTC powered {}".format(params['state'])

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acqusition of data from the PTC.

        Parameters:
            test_mode (bool, optional): Run the Process loop only once.
                This is meant only for testing. Default is False.

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already"
                              "running".format(self.lock.job))
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            while self.take_data:
                # Relinquish sampling lock occasionally
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                # Publish data, waiting 1/f_sample seconds in between calls.
                pub_data = {'timestamp': time.time(),
                            'block_name': 'ptc_status'}
                try:
                    data_flag, data = self.ptc.get_data()
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from compressor. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue
                pub_data['data'] = data
                # If there is an error in compressor output (data_flag = True),
                # do not publish
                if not data_flag:
                    self.agent.publish_to_feed('ptc_status', pub_data)
                time.sleep(1. / self.f_sample)

                if params['test_mode']:
                    break

            self.agent.feeds["ptc_status"].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """Stops acqusition of data from the PTC."""
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
    pgroup.add_argument('--port', default=502)
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--mode', choices=['init', 'acq'])
    pgroup.add_argument('--fake-errors', default=False,
                        help="If True, randomly output 'FAKE ERROR' instead of "
                             "data half of the time.")

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='CryomechCPAAgent',
                                  parser=parser,
                                  args=args)
    print('I am in charge of device with serial number: %s' % args.serial_number)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    # create agent instance and run log creation
    ptc = PTCAgent(agent, args.port, args.ip_address,
                   fake_errors=args.fake_errors)

    agent.register_task('init', ptc.init, startup=init_params)
    agent.register_process('acq', ptc.acq, ptc._stop_acq)
    agent.register_task('power_ptc', ptc.power_ptc)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
