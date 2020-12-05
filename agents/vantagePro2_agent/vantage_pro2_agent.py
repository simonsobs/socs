
import time
import os
import argparse

from typing import Optional
from socs.agent.vantage_pro2.vantage_pro2 import VantagePro2

# from LS240_agent
on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class VantagePro2Agent:

    def __init__(self, agent, port="/dev/ttyUSB0", freq_in=2):
        self.active = True
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.port = port
        self.module: Optional[VantagePro2] = None

        self.freq = freq_in

        self.initialized = False
        self.take_data = False

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('weather_data',
                                 record=True,
                                 agg_params=agg_params)

    # Task functions.
    def init_VantagePro2_task(self, session, params=None):
        """
        Perform first time setup of the Weather Monitor Module.

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.

        """
        if params is None:
            params = {}

        auto_acquire = params.get('auto_acquire', False)

        if self.initialized:
            return True, "Already Initialized Module"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')

            self.module = VantagePro2(self.port)
            print("Initialized Vantage Pro2 module: {!s}".format(
                self.module))

        self.initialized = True

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Vantage Pro2 module initialized.'

    def start_acq(self, session, params=None):
        """
        Method to start data acquisition process.

        Args:
            sample_freq (int):
                Frquency at which weather data is sampled.
                Defaults to sample/2 seconds, the highest frequency possible.

        """
        time.sleep(2)
        if params is None:
            params = {}

        sample_freq = params.get('freq')
        # If loops is None, use value passed to Agent init
        if sample_freq is None:
            sample_freq = self.freq

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'weather',
                    'data': {}
                }

                data['data'] = self.module.weather_daq()
                self.agent.publish_to_feed('weather_data', data)
                time.sleep(sample_freq)

            self.agent.feeds['weather_data'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """

        if self.take_data:
            self.take_data = False
            print('requested to stop taking data.')
            return True, 'data taking succesfully halted'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the Vantage Pro2")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--freq', type=int,
                        help="Sample frequency for weather data collection")
    return parser


if __name__ == "__main__":
    parser = make_parser()
    args = site_config.parse_args(
        agent_class='VantagePro2Agent', parser=parser)
    startup = False

    if args.mode == 'acq':
        startup = True

    agent, runner = ocs_agent.init_site_agent(args)

    vPro2 = VantagePro2Agent(agent, args.port, 2)
    agent.register_task('init', vPro2.init_VantagePro2_task,
                        startup=startup)
    agent.register_process('acq', vPro2.start_acq, vPro2.stop_acq,
                           blocking=True, startup=startup)

    runner.run(agent, auto_reconnect=True)
