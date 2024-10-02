import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

ON_RTD = os.environ.get("READTHEDOCS") == "True"
if not ON_RTD:
    from MC2000B_COMMAND_LIB import *  # noqa: F403
    os.add_dll_directory("C:\\Program Files (x86)\\Thorlabs\\MC2000B\\Sample\\Thorlabs_MC2000B_PythonSDK")

# For logging
txaio.use_twisted()
LOG = txaio.make_logger()

bladetype_keys = {'MC1F2': 0,
                  'MC1F10': 1,
                  'MC1F15': 2,
                  'MC1F30': 3,
                  'MC1F60': 4,
                  'MC1F100': 5,
                  'MC1F10HP': 6,
                  'MC1F2P10': 7,
                  'MC1F6P10': 8,
                  'MC1F10A': 9,
                  'MC2F330': 10,
                  'MC2F47': 11,
                  'MC2F57B': 12,
                  'MC2F860': 13,
                  'MC2F5360': 14}

outputmode_keys = {'target': 0,
                   'actual': 1}

reference_mode_keys = {'internal': 0,
                       'external': 1}

reference_high_prec_mode = {'internalouter': 0,
                            'internalinner': 1,
                            'externalouter': 2,
                            'externalinner': 3}


class ThorlabsMC2000BAgent:
    """Agent to connect to the MC2000B Thorlabs chopper controller
    device.

    Parameters
    ----------
    comport : str
        COM port to connect to device. Ex: "COM3"
    nbaud : int
        baud rate of the device (115200)
    timeout : int
        the timeout time for the device; default is set to 3s
    """

    def __init__(self, agent, comport, nbaud=115200, timeout=3):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.comport = comport
        self.nbaud = nbaud
        self.timeout = timeout

        self.hdl = None

        self.initialized = False
        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feeds
        self.agent.register_feed('chopper_freqs',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_chopper(self, session, params):
        """init_chopper(auto_acquire=False)

        **Task** - Perform first time setup of MC2000B chopper controller
        communication.

        Parameters
        ----------
        auto_acquire : bool, optional
            Default is false. Starts data acquisition after
            initilialization if True.
        """
        if self.initialized:
            return True, "Already initialized"

        with self.lock.acquire_timeout(job='init_chopper') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            # Establish connection to the chopper controller
            self.hdl = MC2000BOpen(self.comport, self.nbaud, self.timeout)

        if (self.hdl == 0):
            self.initialized = True
            self.log.info("Chopper connected")
        else:
            self.initialized = False
            return False, "Chopper not connected"

        # Start data acquisition if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Chopper controller agent initialized"

    @ocs_agent.param('freq', type=float)
    def set_frequency(self, session, params):
        """set_frequency(freq=None)

        **Task** - Set the frequency of the chopper.

        Parameters
        ----------
        freq : float
            Frequency of chopper blades.
        """
        with self.lock.acquire_timeout(timeout=3, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            MC2000BSetFrequency(self.hdl, params['freq'])

        return True, "Chopper frequency set to {} Hz".format(params['freq'])

    @ocs_agent.param('bladetype', type=str, default='MC1F2')
    def set_bladetype(self, session, params):
        """set_bladetype(bladetype=None)

        **Task** - Set the bladetype of the chopper. Selecting a bladetype
        influences the range of frequencies permitted for the chopper.

        Parameters
        ----------
        bladetype : str
            Name of bladetype assigned to chopper controller setup.
            Default set to 'MC1F2' to reach the range of 4-8Hz.
        """
        with self.lock.acquire_timeout(timeout=3, job='set_bladetype') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            bladetype = bladetype_keys[params['bladetype']]
            MC2000BSetBladeType(self.hdl, bladetype)

        return True, "Chopper bladetype set to {}".format(params['bladetype'])

    @ocs_agent.param('output_mode', type=str, choices=['actual', 'target'], default='target')
    def set_reference_output_mode(self, session, params):
        """set_reference_output_mode(output_mode=None)

        **Task** - Set the output reference mode to determine the setting of
        frequency output/input.

        Parameters
        ----------
        output_mode : str
            Output reference mode of chopper frequency. Possible modes
            are 'target' or 'actual'. Default set to 'target'.

        """
        with self.lock.acquire_timeout(timeout=3, job='set_reference_output_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            mode = params['output_mode']
            mode_int = outputmode_keys[mode]
            MC2000BSetReferenceOutput(self.hdl, mode_int)

        return True, "Chopper output mode set to {}".format(params['output_mode'])

    @ocs_agent.param('reference', type=str, default='internalinner')
    def set_blade_reference(self, session, params):
        """set_blade_reference(reference=None)

        **Task** - Set the reference mode for the blade. This is the point on
        the chopper blades for the controller to measure and set frequency.

        Parameters
        ----------
        reference : str
            Reference mode of the blade. Default set to 'internalinner'.
            Can be "internal", "external", "internalinner", "internalouter",
            "externalinner", "externalouter"
        """
        with self.lock.acquire_timeout(timeout=3, job='set_blade_reference') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            reference = params['reference']

            if reference in ('external', 'internal'):
                ref = reference_mode_keys[reference]
            else:
                ref = reference_high_prec_mode[reference]

            MC2000BSetReference(self.hdl, ref)

        return True, "Chopper blade reference set to {}".format(params['reference'])

    def acq(self, session, params):
        """acq()

        **Process** - Acquire data from the MC2000B chopper device.

        """
        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} "
                              "is already running")
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            self.log.info("Starting data acquisition for {}".format(self.agent.agent_address))

            while self.take_data:
                # Relinquish sampling lock occasionally
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                freq_in = [0]
                MC2000BGetFrequency(self.hdl, freq_in)
                input_freq = freq_in[0]

                freq_out = [0]
                MC2000BGetReferenceOutFrequency(self.hdl, freq_out)
                output_freq = freq_out[0]

                # Publish data
                chopper_freqs = {'block_name': 'chopper_freqs',
                                 'timestamp': time.time(),
                                 'data': {'input_freqs': input_freq,
                                          'output_freqs': output_freq}
                                 }

                self.agent.publish_to_feed('chopper_freqs', chopper_freqs)

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            session.set_status('stopping')
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'


def make_parser(parser=None):
    """Build argument parser for the Agent
    """

    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--com-port')
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='ThorlabsMC2000BAgent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    controller_agent = ThorlabsMC2000BAgent(agent, args.com_port)

    agent.register_task('init_chopper', controller_agent.init_chopper, startup=init_params)
    agent.register_task('set_frequency', controller_agent.set_frequency)
    agent.register_task('set_bladetype', controller_agent.set_bladetype)
    agent.register_task('set_reference_output_mode', controller_agent.set_reference_output_mode)
    agent.register_task('set_blade_reference', controller_agent.set_blade_reference)
    agent.register_process('acq', controller_agent.acq, controller_agent._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
