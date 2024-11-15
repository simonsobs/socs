import argparse
import os
import time
import warnings
from typing import Optional

import txaio

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
    def init_lakeshore(self, session, params=None):
        """init_lakeshore(auto_acquire=False)

        **Task** - Perform first time setup of the Lakeshore 240 Module.

        Parameters:
            auto_acquire (bool, optional): Starts data acquisition after
                initialization if True. Defaults to False.

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

            self.module = Module(port=self.port)
            print("Initialized Lakeshore module: {!s}".format(self.module))
            session.add_message("Lakeshore initialized with ID: %s" % self.module.inst_sn)

        self.initialized = True

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Lakeshore module initialized.'

    def set_values(self, session, params=None):
        """set_values(channel, sensor=None, auto_range=None, range=None,\
                current_reversal=None, units=None, enabled=None, name=None)

        **Task** - Set sensor parameters for a Lakeshore240 Channel.

        Args:
            channel (int):
                Channel number to set. Valid choices are 1-8.
            sensor (int, optional):
                Specifies sensor type.  See
                :func:`socs.Lakeshore.Lakeshore240.Channel.set_values` for
                possible types.
            auto_range (int, optional):
                Specifies if channel should use autorange. Must be 0 or 1.
            range (int, optional):
                Specifies range if auto_range is false. Only settable for NTC
                RTD.  See
                :func:`socs.Lakeshore.Lakeshore240.Channel.set_values` for
                possible ranges.
            current_reversal (int, optional):
                Specifies if input current reversal is on or off.
                Always 0 if input is a diode.
            units (int, optional):
                Specifies preferred units parameter, and sets the units for
                alarm settings.  See
                :func:`socs.Lakeshore.Lakeshore240.Channel.set_values` for
                possible units.
            enabled (int, optional):
                Sets if channel is enabled.
            name (str, optional):
                Sets name of channel.

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
        """upload_cal_curve(channel, filename)

        **Task** - Upload a calibration curve to a channel.

        Parameters:
            channel (int): Channel number, 1-8.
            filename (str): Filename for calibration curve.

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

    def acq(self, session, params=None):
        """acq(sampling_frequency=2.5)

        **Process** - Start data acquisition.

        Parameters:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz


        The most recent data collected is stored in session data in the
        structure::

            >>> response.session['data']
            {"fields":
                {"Channel_1": {"T": 99.26, "V": 99.42},
                 "Channel_2": {"T": 99.54, "V": 101.06},
                 "Channel_3": {"T": 100.11, "V":100.79},
                 "Channel_4": {"T": 98.49, "V": 100.77},
                 "Channel_5": {"T": 97.75, "V": 101.45},
                 "Channel_6": {"T": 99.58, "V": 101.75},
                 "Channel_7": {"T": 98.03, "V": 100.82},
                 "Channel_8": {"T": 101.14, "V":101.01}},
             "timestamp":1601925677.6914878}

        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency')
        # If f_sample is None, use value passed to Agent init
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1 / f_sample - 0.01

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            self.take_data = True

            session.data = {"fields": {}}

            while self.take_data:
                current_time = time.time()
                data = {
                    'timestamp': current_time,
                    'block_name': 'temps',
                    'data': {}
                }

                for chan in self.module.channels:
                    # Read sensor on channel
                    chan_string = "Channel_{}".format(chan.channel_num)
                    temp_reading = chan.get_reading(unit='K')
                    sensor_reading = chan.get_reading(unit='S')

                    # For data feed
                    data['data'][chan_string + '_T'] = temp_reading
                    data['data'][chan_string + '_V'] = sensor_reading

                    # For session.data
                    field_dict = {chan_string: {"T": temp_reading, "V": sensor_reading}}
                    session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('temperatures', data)

                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['temperatures'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
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

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--serial-number', type=str,
                        help="Serial number of your Lakeshore240 device")
    pgroup.add_argument('--port', type=str,
                        help="Path to USB node for the lakeshore")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument('--sampling-frequency', type=float,
                        help="Sampling frequency for data acquisition")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Not used anymore, but we don't it to break the agent if these args are passed
    parser.add_argument('--fake-data', help=argparse.SUPPRESS)
    parser.add_argument('--num-channels', help=argparse.SUPPRESS)

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='Lakeshore240Agent',
                                  parser=parser,
                                  args=args)

    if args.fake_data is not None:
        warnings.warn("WARNING: the --fake-data parameter is deprecated, please "
                      "remove from your site-config file", DeprecationWarning)

    if args.num_channels is not None:
        warnings.warn("WARNING: the --num-channels parameter is deprecated, please "
                      "remove from your site-config file", DeprecationWarning)

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

    agent.register_task('init_lakeshore', therm.init_lakeshore,
                        startup=init_params)
    agent.register_task('set_values', therm.set_values)
    agent.register_task('upload_cal_curve', therm.upload_cal_curve)
    agent.register_process('acq', therm.acq, therm._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
