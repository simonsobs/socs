import argparse
import socket
import time
from os import environ

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.srs_cg635.drivers import SRSCG635Interface


class SRSCG635Agent:
    """Class to retrieve data from the SRS CG635 clock.

    Parameters
    ----------
    agent : ocs_agent.OCSAgent
        Instantiated OCSAgent class for this Agent.
    ip_address : str
        IP address of the Prologix GPIB interface.
    gpib_slot : int
        GPIB address set on the SRS CG635.
    """

    def __init__(self, agent, ip_address, gpib_slot):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.gpib_slot = gpib_slot
        self.monitor = False

        self.clock = None

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 10 * 60,
        }
        self.agent.register_feed('srs_clock',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init(auto_acquire=False)

        **Task** - Initialize the connection to the srs clock.

        Parameters
        ----------
        auto_acquire: bool, optional
            Default is False. Starts data acquisition after initialization
            if True.
        """
        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.clock = SRSCG635Interface(self.ip_address, self.gpib_slot)
                self.idn = self.clock.identify()

            except socket.timeout as e:
                self.log.error(f"Clock timed out during connect: {e}")
                return False, "Timeout"
            self.log.info("Connected to Clock: {}".format(self.idn))

        # Start data acquisition if requested in site-config
        auto_acquire = params.get('auto_acquire', False)
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Initialized Clock.'

    @ocs_agent.param('test_mode', default=False, type=bool)
    @ocs_agent.param('wait', default=1, type=float)
    def acq(self, session, params):
        """acq(wait=1, test_mode=False)

        **Process** - Continuously monitor srs clock lock registers
        and publish to a feed.

        The ``session.data`` object stores the most recent published values
        in a dictionary. For example::

            session.data = {
                'timestamp': 1598626144.5365012,
                'block_name': 'clock_output',
                'data': {
                    'Frequency': 122880000.0
                    'Standard_CMOS_Output': 3,
                    'Running_State': 1,
                    'Timebase': 3,
                    'PLL_RF_UNLOCKED': 1,
                    'PLL_19MHZ_UNLOCKED': 1,
                    'PLL_10MHz_UNLOCKED': 0,
                    'PLL_RB_UNLOCKED': 1,
                    'PLL_OUT_UNLOCKED': 0,
                    'PLL_Phase_Shift': 0,
                }
            }

        Refer to drivers for interpretation of outputs.

        Parameters
        ----------
        wait: float, optional
            time to wait between measurements [seconds]. Default=1s.

        """
        self.monitor = True

        while self.monitor:
            with self.lock.acquire_timeout(1) as acquired:
                if acquired:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'clock_output',
                        'data': {}
                    }

                    try:
                        data['data']['Frequency'] = self.clock.get_freq()
                        data['data']['Standard_CMOS_Output'] = self.clock.get_stdc()
                        data['data']['Running_State'] = self.clock.get_runs()
                        data['data']['Timebase'] = self.clock.get_timebase()

                        # get_lock_statuses returns a dict of the register bits
                        # Loop through the items to add each to the data
                        lock_statuses = self.clock.get_lock_statuses()
                        for register, status in lock_statuses.items():
                            # Not adding PLL causes a naming error
                            # Two of the registers start with an number
                            data['data']["PLL_" + register] = status

                    except ValueError as e:
                        self.log.error(f"Error in collecting data: {e}")
                        continue

                    self.agent.publish_to_feed('srs_clock', data)

                    # Allow this process to be queried to return current data
                    session.data = data

                else:
                    self.log.warn("Could not acquire in monitor clock")

            time.sleep(params['wait'])

            if params['test_mode']:
                break

        return True, "Finished monitoring clock"

    def _stop_acq(self, session, params):
        """Stop monitoring the clock output."""
        if self.monitor:
            self.monitor = False
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
    pgroup.add_argument('--ip-address', type=str, help="Internal GPIB IP Address")
    pgroup.add_argument('--gpib-slot', type=int, help="Internal SRS GPIB Address")
    pgroup.add_argument('--mode', type=str, help="Set to acq to run acq on "
                        + "startup")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = site_config.add_arguments()

    # Get the default ocs agrument parser
    parser = make_parser()

    args = site_config.parse_args(agent_class='SRSCG635Agent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = SRSCG635Agent(agent, args.ip_address, int(args.gpib_slot))

    agent.register_task('init', p.init, startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
