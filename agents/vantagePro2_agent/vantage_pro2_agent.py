
import time
import os
import argparse

from typing import Optional
from socs.agent.vantage_pro2.vantage_pro2 import VantagePro2

# from LS240_agent
on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import Pacemaker
    from ocs.ocs_twisted import TimeoutLock


class VantagePro2Agent:
    """Agent to connect to single VantagePro2 Weather Monitor Device.

    Args:
        sample_freq (double):
             frequency (Hz) at which the weather monitor samples data. Can not
             be faster than 0.5 Hz. This value is converted to period (sec) for
             time.wait(seconds)
        port (string):
             usb port that the weather monitor is connected to.  The monitor
             will communicate via this port.
    """
    # change port argument when I figure out how to generalize it!
    def __init__(self, agent, port="/dev/ttyUSB0", sample_freq=0.5):
        self.active = True
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.port = port
        self.module: Optional[VantagePro2] = None

        if sample_freq > 0.5:
            self.log.warn("Sample frequency too fast! Setting to 0.5Hz")
            sample_freq = 0.5
        self.sample_freq = sample_freq

        self.initialized = False
        self.take_data = False

        # Registers weather data feed
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

        time.sleep(2)

        return True, 'Vantage Pro2 module initialized.'

    def start_acq(self, session, params=None):
        """
        Method to start data acquisition process.

        Args:
            sample_freq (double):
                Frequency at which weather data is sampled.
                Defaults to 0.5 Hz.

        """
        if params is None:
            params = {}

        sample_freq = params.get('sample_freq')
        # If loops is None, use value passed to Agent init
        if sample_freq is None:
            sample_freq = self.sample_freq
        wait_time = 1/sample_freq

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("""Could not start acq because {} is
                already running"""
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')
            # use pacemaker class to take data at regular intervals
            if sample_freq % 1 == 0:
                pm = Pacemaker(sample_freq, True)
            else:
                pm = Pacemaker(sample_freq)

            self.take_data = True

            while self.take_data:
                pm.sleep()
                data = {
                    'timestamp': time.time(),
                    'block_name': 'weather',
                    'data': {}
                }
                data['data'] = self.module.weather_daq()
                self.agent.publish_to_feed('weather_data', data)
                time.sleep(wait_time)

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
    pgroup.add_argument('--serial-number', type=str,
                        help="Serial number of VantagePro2 Monitor")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--sample_freq', type=float,
                        help="Sample frequency for weather data collection")
    return parser


def main():
    parser = make_parser()
    args = site_config.parse_args(
        agent_class='VantagePro2Agent', parser=parser)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    device_port = None

    if args.port is not None:
        device_port = args.port
    else:  # Tries to find correct USB port automatically

        # This exists if udev rules are setup properly for the 240s
        if os.path.exists('/dev/{}'.format(args.serial_number)):
            device_port = "/dev/{}".format(args.serial_number)

        elif os.path.exists('/dev/serial/by-id'):
            ports = os.listdir('/dev/serial/by-id')
            for port in ports:
                if args.serial_number in port:
                    device_port = "/dev/serial/by-id/{}".format(port)
                    print("Found port {}".format(device_port))
                    break

    if device_port is None:
        print("Could not find device port for {}".format(args.serial_number))
        return

    agent, runner = ocs_agent.init_site_agent(args)

    vPro2 = VantagePro2Agent(agent, device_port, args.sample_freq)
    agent.register_task('init', vPro2.init_VantagePro2_task,
                        startup=init_params)
    agent.register_process('acq', vPro2.start_acq, vPro2.stop_acq,
                           blocking=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
