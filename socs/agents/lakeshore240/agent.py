import argparse
import os
import time
import warnings
from typing import Optional
import queue
from dataclasses import dataclass, field
from enum import Enum
from twisted.internet import defer
import txaio
txaio.use_twisted()
from ocs.ocs_twisted import Pacemaker

from socs.Lakeshore.Lakeshore240 import Module

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class Actions:
    class BaseAction:
        def __post_init__(self):
            self.defered = defer.Deferred()
            self.log = txaio.make_logger()

        def process(self, *args, **kwargs):
            raise NotImplementedError

    @dataclass
    class UploadCalCurve(BaseAction):
        channel: int
        filename: str

        def process(self, module, log=None):
            if log is None:
                log = self.log

            log.info(f"Starting upload to channel {self.channel}...")
            channel = module.channels[self.channel - 1]
            channel.load_curve(self.filename)
            time.sleep(0.1)
            return True

    @dataclass
    class SetValues(BaseAction):
        channel: int
        sensor: Optional[int] = None
        auto_range: Optional[int] = None
        range: Optional[int] = None
        current_reversal: Optional[int] = None
        unit: Optional[int] = None
        enabled: Optional[int] = None
        name: Optional[str] = None

        def process(self, module, log=None):
            if log is None:
                log = self.log

            log.info(f"Setting values for channel {self.channel}...")
            module.channels[self.channel - 1].set_values(
                sensor=self.sensor,
                auto_range=self.auto_range,
                range=self.range,
                current_reversal=self.current_reversal,
                unit=self.unit,
                enabled=self.enabled,
                name=self.name,
            )
            time.sleep(0.1)
            return True

class LS240_Agent:
    def __init__(self, agent, port="/dev/ttyUSB0", f_sample=2.5):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.port = port
        self.f_sample = f_sample
        self.action_queue = queue.Queue()

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed(
            'temperatures', record=True,
            agg_params=agg_params, buffer_time=1
        )

    def _init_lakeshore(self):
        """
        Creates new lakeshore module
        """
        module = Module(port=self.port)
        self.log.info("Lakeshore initialized with ID: %s" % module.inst_sn)
        return module

    @defer.inlineCallbacks
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
        action = Actions.SetValues(**params)
        self.action_queue.put(action)
        session.data = yield action.defered
        return True, f"Set values for channel {action.channel}"

    @defer.inlineCallbacks
    def upload_cal_curve(self, session, params=None):
        """upload_cal_curve(channel, filename)

        **Task** - Upload a calibration curve to a channel.

        Parameters:
            channel (int): Channel number, 1-8.
            filename (str): Filename for calibration curve.
        """
        action = Actions.UploadCalCurve(**params)
        self.action_queue.put(action)
        session.data = yield action.defered
        return True, f"Uploaded curve to channel {action.channel}"

    def _get_and_pub_temp_data(self, module: Module, session: ocs_agent.OpSession):
        """
        Gets temperature data from the LS240, publishes to OCS feed, and updates
        session.data
        """
        current_time = time.time()
        data = {
            'timestamp': current_time,
            'block_name': 'temps',
            'data': {}
        }
        # Get Temps
        field_dict = {}
        for chan in module.channels:
            # Read sensor on channel
            chan_string = "Channel_{}".format(chan.channel_num)
            temp_reading = chan.get_reading(unit='K')
            sensor_reading = chan.get_reading(unit='S')

            # For data feed
            data['data'][chan_string + '_T'] = temp_reading
            data['data'][chan_string + '_V'] = sensor_reading

            # For session.data
            field_dict[chan_string] = {"T": temp_reading, "V": sensor_reading}

        session.data['fields'] = field_dict
        self.agent.publish_to_feed('temperatures', data)
        session.data['timestamp'] = current_time
        return data

    def _process_actions(self, module: Module):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            try:
                self.log.info(f"Running action {action}")
                res = action.process(module)
                action.defered.callback(res)
            except Exception as e:
                self.log.error(f"Error processing action: {action}")
                action.defered.errback(e)

    def main(self, session: ocs_agent.OpSession, params=None):
        """
        **Process** - Main process for the Lakeshore240 agent.
        Gets temperature data at specified sample rate, and processes commands.
        """
        module: Optional[Module] = None
        session.set_status('running')
        pm = Pacemaker(self.f_sample, quantize=False)
        while session.status in ['starting', 'running']:
            if module is None:
                try:
                    module = self._init_lakeshore()
                except ConnectionRefusedError:
                    self.log.error(
                        "Could not connect to Lakeshore. "
                        "Retrying after 30 sec..."
                    )
                    time.sleep(30)
                    pm.sleep()
                    continue

            try:
                self._get_and_pub_temp_data(module, session)
                self._process_actions(module)
            except (ConnectionError, TimeoutError):
                self.log.error("Connection to Lakeshore lost. Attempting to reconnect...")
                module = None

        return True, "Ended main process"

    def _stop_main(self, session, params=None):
        session.set_status('stopping')
        return True, 'Requesting to stop main process'


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

    if args.mode is not None:
        warnings.warn(
            "WARNING: the --init-mode parameter is deprecated, please "
            "remove from your site-config file", DeprecationWarning)

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
    agent.register_task('set_values', therm.set_values, blocking=False)
    agent.register_task('upload_cal_curve', therm.upload_cal_curve, blocking=False)
    agent.register_process('main', therm.main, therm._stop_main, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
