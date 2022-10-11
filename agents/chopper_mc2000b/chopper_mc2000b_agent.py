import time
import os
from os import environ

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as dsleep
import argparse
import txaio

from MC2000B_COMMAND_LIB import *

os.environ['OCS_CONFIG_DIR'] = "C:\\ocs-site-configs\\"
os.add_dll_directory("C:\Program Files (x86)\Thorlabs\MC2000B\Sample\Thorlabs_MC2000B_PythonSDK")

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


class ControllerAgent:
    """Agent to connect to the MC2000B ThorLabs Chopper Controller
    device.

    Parameters
    __________

    comport : str
        COM port to connect to device
        Ex: "COM3"
    nbaud : int
        baud rate of the device
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

        self.hdl = MC2000BOpen(self.comport, self.nbaud, self.timeout)

        self.initialized = False
        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feeds
        self.agent.register_feed('input_freqs',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

        self.agent.register_feed('output_freqs',
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
        __________

        auto_acquire : (bool, optional)
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

            session.set_status('running')

            # Establish connection to the chopper controller
            self.hdl = MC2000BOpen(self.comport, self.nbaud, self.timeout)

        if(self.hdl == 0):
            self.initialized = True
            self.log.info("Chopper connected")
        else:
            self.log.warn("Chopper not connected")

        # Start data acquisition if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Chopper controller agent initialized"

    @ocs_agent.param('freq', type=int)
    def set_frequency(self, session, params):
        """set_frequency(freq=None)

        **Task** - Set the frequency of the chopper blades.

        Parameters
        __________
        freq : int
            Frequency desired for the chopper blades of the device.
        """
        with self.lock.acquire_timeout(timeout=3, job='set_frequency') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            MC2000BSetFrequency(self.hdl, params['freq'])

        return True, "Chopper frequency set to {} Hz".format(params['freq'])

    @ocs_agent.param('bladetype', type=str, default='MC1F2')
    def set_bladetype(self, session, params):
        """set_bladetype(bladetype=None)

        **Task** - Set the bladetype for the chopper controller. Bladetype
            determines range of frequencies that can be set for the chopper.
            Default set to MC1F2 to reach the range of 4-8Hz.

        Parameters
        __________
        blaetype : str
            Name of bladetype assigned to chopper controller setup.
            Ex: "MC1F6P10"
        """
        with self.lock.acquire_timeout(timeout=3, job='set_bladetype') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')
   
            bladetype = bladetype_keys[params['bladetype']]
            MC2000BSetBladeType(self.hdl, bladetype)

        return True, "Chopper bladetype set to {}".format(params['bladetype'])

    @ocs_agent.param('output_mode', type=str, choices=['actual', 'target'], default='target')
    def set_reference_output_mode(self, session, params):
        """set_reference_output_mode(output_mode=None)

        **Task** - Set the output reference mode to determine the setting of
            frequency output/input. Default set to 'target'.
        """
        with self.lock.acquire_timeout(timeout=3, job='set_reference_output_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            mode = params['output_mode']
            mode_int = outputmode_keys[mode]
            MC2000BSetReferenceOutput(self.hdl, mode_int)

        return True, "Chopper output mode set to {}".format(params['output_mode'])

    @ocs_agent.param('reference', type=str, default='internalinner')
    def set_blade_reference(self, session, params):
        """set_blade_reference(reference=None)

        **Task** - Set the reference mode for the blade. Default set to
            'internalinner'.
        """
        with self.lock.acquire_timeout(timeout=3, job='set_blade_reference') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

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

            session.set_status('running')

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
                input_data = {'block_name': 'input_freqs',
                              'timestamp' : time.time(),
                              'data': {'input_freqs': input_freq}
                             }
                output_data = {'block_name': 'output_freqs',
                               'timestamp': time.time(),
                               'data': {'output_freqs': output_freq}
                              }

                self.agent.publish_to_feed('input_freqs', input_data)
                self.agent.publish_to_feed('output_freqs', output_data)

    def stop_acq(self):
        ok = False
        with self.lock:
            if self.job =='acq':
                self.job = '!acq'
                ok = True
            return (ok, {True: 'Requested process stop.', False: 'Faied to request process stop.'}[ok])

def make_parser(parser=None):
    """Build argument parser for the Agent
    """

    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--comport')
    pgroup.add_argument('--mode', choices=['init', 'acq'])

    return parser

if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='ControllerAgent', parser=parser)

    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    controller_agent = ControllerAgent(agent, args.comport)

    agent.register_task('init_chopper', controller_agent.init_chopper, startup=init_params)
    agent.register_task('set_frequency', controller_agent.set_frequency)
    agent.register_task('set_bladetype', controller_agent.set_bladetype)
    agent.register_task('set_reference_output_mode', controller_agent.set_reference_output_mode)
    agent.register_task('set_blade_reference', controller_agent.set_blade_reference)
    agent.register_process('acq', controller_agent.acq, controller_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)

