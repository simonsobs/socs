
import time
import os
import argparse
import warnings
import txaio

from typing import Optional

from weather_monitor import WeatherMonitor

# from LS240_agent
on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class WeatherMonitorAgent:

    def __init__(self, agent, port="/dev/ttyUSB0", loops=1):
        self.active = True
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.port = port
        self.module: Optional[WeatherMonitor] = None

        self.loops = loops

        self.initialized = False
        self.take_data = False

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('weather_data',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    # Task functions.

    def init_weather_monitor_task(self, session, params=None):
        """init_weather_monitor_task(params=None)

        Perform first time setup of the Weather Monitor Module.

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.

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

            self.module = WeatherMonitor(self.port)
            print("Initialized Weather Monitor module: {!s}".format(
                self.module))

        self.initialized = True

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Weather Monitor module initialized.'

    def start_acq(self, session, params=None):
        """acq(params=None)

        Method to start data acquisition process.

        Args:
            loops (int):
                How many data points are to be collected per call. Defaults to 1.

        """
        time.sleep(2)
        if params is None:
            params = {}

        loops = params.get('loops')
        # If loops is None, use value passed to Agent init
        if loops is None:
            loops = self.loops

        sleep_time = 2

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
                    'block_name': 'temps',
                    'data': {}
                }

                for i in range(0, loops):
                    data['data'] = self.module.weather_daq(loops)[i]
                    self.agent.publish_to_feed('weather_data', data)
                print("data published!")

                time.sleep(sleep_time)

            self.agent.feeds['weather_data'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            print('requested to stop taking data.')
            self.module.interrupt_daq()
            return True, 'data taking succesfully halted'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the weather monitor")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--loops', type=int,
                        help="How many data points to collect per data acquisition call")
    return parser


if __name__ == "__main__":
    parser = make_parser()
    args = site_config.parse_args(
        agent_class='WeatherMonitorAgent', parser=parser)
    startup = False

    if args.mode == 'acq':
        startup = True

    agent, runner = ocs_agent.init_site_agent(args)

    path = '/dev'
    for fname in os.listdir(path):
        if fname[0:6] == 'ttyUSB':
            usb = os.path.join(path, fname)
            path += usb

    print(path)

    wMonitor = WeatherMonitorAgent(agent, args.port, args.loops)
    agent.register_task('init_weathermonitor', wMonitor.init_weather_monitor_task,
                        startup=startup)
    agent.register_process('acq', wMonitor.start_acq, wMonitor.stop_acq,
                           blocking=True, startup=startup)

    runner.run(agent, auto_reconnect=True)