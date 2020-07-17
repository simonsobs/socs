import time
import os
import argparse
import warnings
import txaio

from typing import Optional

from socs.Lakeshore.Lakeshore240 import Module

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class LS240_Agent:

    def __init__(self, agent, port="/dev/ttyUSB0", f_sample=2.5):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.port = port
        self.module: Optional[Module] = None

        self.f_sample = f_sample

        self.initialized = False
        self.take_data = False

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    # Task functions.
    def init_lakeshore_task(self, session, params=None):
        """init_lakeshore_task(params=None)

        Perform first time setup of the Lakeshore 240 Module.

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

            self.module = Module(port=self.port)
            print("Initialized Lakeshore module: {!s}".format(self.module))
            session.add_message("Lakeshore initialized with ID: %s"%self.module.inst_sn)

        self.initialized = True

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Lakeshore module initialized.'

    def set_values(self, session, params=None):
        """set_values(params=None)

        A task to set sensor parameters for a Lakeshore240 Channel

        Args:
            channel (int, 1 -- 2 or 8):
                Channel number to  set.
            sensor (int, 1, 2, or 3, optional):
                Specifies sensor type:
                    +---+---------+
                    | 1 | Diode   |
                    +---+---------+
                    | 2 | PlatRTC |
                    +---+---------+
                    | 3 | NTC RTD |
                    +---+---------+
            auto_range (int, 0 or 1, optional):
                Must be 0 or 1. Specifies if channel should use autorange.
            range (int 0-8, optional):
                Specifies range if autorange is false. Only settable for NTC RTD:
                    +---+--------------------+
                    | 0 | 10 Ohms (1 mA)     |
                    +---+--------------------+
                    | 1 | 30 Ohms (300 uA)   |
                    +---+--------------------+
                    | 2 | 100 Ohms (100 uA)  |
                    +---+--------------------+
                    | 3 | 300 Ohms (30 uA)   |
                    +---+--------------------+
                    | 4 | 1 kOhm (10 uA)     |
                    +---+--------------------+
                    | 5 | 3 kOhms (3 uA)     |
                    +---+--------------------+
                    | 6 | 10 kOhms (1 uA)    |
                    +---+--------------------+
                    | 7 | 30 kOhms (300 nA)  |
                    +---+--------------------+
                    | 8 | 100 kOhms (100 nA) |
                    +---+--------------------+
            current_reversal (int, 0 or 1, optional):
                Specifies if input current reversal is on or off.
                Always 0 if input is a diode.
            units (int, 1-4, optional):
                Specifies preferred units parameter, and sets the units
                for alarm settings:
                    +---+------------+
                    | 1 | Kelvin     |
                    +---+------------+
                    | 2 | Celsius    |
                    +---+------------+
                    | 3 | Sensor     |
                    +---+------------+
                    | 4 | Fahrenheit |
                    +---+------------+
            enabled (int, 0 or 1, optional):
                sets if channel is enabled
            name (str, optional):
                sets name of channel
        """
        if params is None:
            params = {}

        with self.lock.acquire_timeout(0, job='set_values') as acquired:
            if not acquired:
                self.log.warn("Could not start set_values because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.module.channels[params['channel'] - 1].set_values(
                sensor=params.get('sensor'),
                auto_range=params.get('auto_range'),
                range=params.get('range'),
                current_reversal=params.get('current_reversal'),
                unit=params.get('unit'),
                enabled=params.get('enabled'),
                name=params.get('name'),
            )

        return True, 'Set values for channel {}'.format(params['channel'])

    def upload_cal_curve(self, session, params=None):
        """
        Task to upload a calibration curve to a channel.

        Args:

            channel (int, 1 -- 2 or 8): Channel number
            filename (str): filename for cal curve
        """

        channel = params['channel']
        filename = params['filename']

        with self.lock.acquire_timeout(0, job='upload_cal_curve') as acquired:
            if not acquired:
                self.log.warn("Could not start set_values because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            channel = self.module.channels[channel - 1]
            self.log.info("Starting upload to channel {}...".format(channel))
            channel.load_curve(filename)
            self.log.info("Finished uploading.")

        return True, "Uploaded curve to channel {}".format(channel)

    def start_acq(self, session, params=None):
        """acq(params=None)

        Method to start data acquisition process.

        Args:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz

        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency')
        # If f_sample is None, use value passed to Agent init
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1/f_sample - 0.01

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

                for chan in self.module.channels:
                    chan_string = "Channel_{}".format(chan.channel_num)
                    data['data'][chan_string + '_T'] = chan.get_reading(unit='K')
                    data['data'][chan_string + '_V'] = chan.get_reading(unit='S')

                self.agent.publish_to_feed('temperatures', data)

                time.sleep(sleep_time)

            self.agent.feeds['temperatures'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Config')
    pgroup.add_argument('--serial-number', type=str,
                        help="Serial number of your Lakeshore240 device")
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the lakeshore")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--sampling-frequency', type=float,
                        help="Sampling frequency for data acquisition")

    return parser


def main():
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    p = site_config.add_arguments()
    parser = make_parser(parser=p)

    #Not used anymore, but we don't it to break the agent if these args are passed
    parser.add_argument('--fake-data', help=argparse.SUPPRESS)
    parser.add_argument('--num-channels', help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.fake_data is not None:
        warnings.warn("WARNING: the --fake-data parameter is deprecated, please "
                      "remove from your site-config file", DeprecationWarning)

    if args.num_channels is not None:
        warnings.warn("WARNING: the --num-channels parameter is deprecated, please "
            "remove from your site-config file", DeprecationWarning)

    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Lakeshore240Agent')

    # Automatically acquire data if requested (default)
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

    kwargs = {
        'port': device_port
    }

    if args.sampling_frequency is not None:
        kwargs['f_sample'] = float(args.sampling_frequency)

    therm = LS240_Agent(agent, **kwargs)

    agent.register_task('init_lakeshore', therm.init_lakeshore_task,
                        startup=init_params)
    agent.register_task('set_values', therm.set_values)
    agent.register_task('upload_cal_curve', therm.upload_cal_curve)
    agent.register_process('acq', therm.start_acq, therm.stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
