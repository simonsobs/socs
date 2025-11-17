import argparse
import os
import queue
import time
import traceback
import warnings
from dataclasses import dataclass
from typing import Any, Dict, Optional

import txaio  # type: ignore
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker

from socs.actions import BaseAction, OcsOpReturnType, register_task_from_action
from socs.Lakeshore.Lakeshore240 import Module

txaio.use_twisted()


on_rtd = os.environ.get("READTHEDOCS") == "True"
if not on_rtd:
    log = txaio.make_logger()  # pylint: disable=E1101


class LS240Action(BaseAction):
    def process(self, module: Module) -> None:
        raise NotImplementedError


@dataclass
class UploadCalCurve(LS240Action):
    """
    **OCS Task**

    Action class to Upload a calibration curve to a channel. This is an OCS
    Task that can be run through a client as follows::

        >> client.upload_cal_curve(channel=channel, filename=filename)

    Args
    ------
    channel (int):
        Channel number, 1-8.
    filename (str):
        Filename for calibration curve.
    """
    channel: int
    filename: str

    def process(self, module: Module) -> None:
        log.info(f"Starting upload to channel {self.channel}...")
        channel = module.channels[self.channel - 1]
        channel.load_curve(self.filename)
        time.sleep(0.1)


@dataclass
class SetValues(LS240Action):
    """
    **OCS TASK**

    Action class for setting sensor parameters for a Lakeshore240 Channel.
    This can be called through an OCS client using::

        >> client.set_values(
            channel=channel,
            sensor=sensor,
            auto_range=auto_range,
            range=range,
            current_reversal=current_reversal,
            units=units,
            enabled=enabled,
            name=name,
        )

    Args
    ---------
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

    channel: int
    sensor: Optional[int] = None
    auto_range: Optional[int] = None
    range: Optional[int] = None
    current_reversal: Optional[int] = None
    units: Optional[int] = None
    enabled: Optional[int] = None
    name: Optional[str] = None

    def process(self, module: Module) -> None:
        log.info(f"Setting values for channel {self.channel}...")
        module.channels[self.channel - 1].set_values(
            sensor=self.sensor,
            auto_range=self.auto_range,
            range=self.range,
            current_reversal=self.current_reversal,
            unit=self.units,
            enabled=self.enabled,
            name=self.name,
        )
        time.sleep(0.1)


class LS240_Agent:
    def __init__(
        self,
        agent: ocs_agent.OCSAgent,
        port: str = "/dev/ttyUSB0",
        f_sample: float = 2.5,
    ) -> None:
        self.agent: ocs_agent.OCSAgent = agent
        self.port = port
        self.f_sample = f_sample
        self.action_queue: "queue.Queue[LS240Action]" = queue.Queue()

        def queue_action(action: LS240Action):
            self.action_queue.put(action)

        # Register Operations
        register_task_from_action(
            agent, "set_values", SetValues, queue_action
        )
        register_task_from_action(
            agent, "upload_cal_curve", UploadCalCurve, queue_action
        )
        agent.register_process("main", self.main, self._stop_main, startup=True)

        # Registers Temperature and Voltage feeds
        agg_params = {
            "frame_length": 60,
        }
        self.agent.register_feed(
            "temperatures", record=True, agg_params=agg_params, buffer_time=1
        )

    def _get_and_pub_temp_data(
        self, module: Module, session: ocs_agent.OpSession
    ) -> Dict[str, Any]:
        """
        Gets temperature data from the LS240, publishes to OCS feed, and updates
        session.data
        """
        current_time = time.time()
        # Get Temps
        field_dict = {}
        data_dict = {}
        for chan in module.channels:
            # Read sensor on channel
            chan_string = f"Channel_{chan.channel_num}"
            temp_reading = chan.get_reading(unit="K")
            sensor_reading = chan.get_reading(unit="S")

            # For data feed
            data_dict[chan_string + "_T"] = temp_reading
            data_dict[chan_string + "_V"] = sensor_reading

            # For session.data
            field_dict[chan_string] = {"T": temp_reading, "V": sensor_reading}

        data = {
            "timestamp": current_time,
            "block_name": "temps",
            "data": data_dict,
        }

        session.data["fields"] = field_dict
        self.agent.publish_to_feed("temperatures", data)
        session.data["timestamp"] = current_time
        return data

    def _process_actions(self, module: Module) -> None:
        """
        Processes queued actions using the provided Lakeshore Module.
        """
        while not self.action_queue.empty():
            action = self.action_queue.get()
            try:
                log.info(f"Running action {action}")
                action.process(module)
                action.resolve_action(True)
            except Exception:  # pylint: disable=broad-except
                log.error(f"Error processing action: {action}")
                action.resolve_action(
                    False,
                    traceback=traceback.format_exc(),
                    return_message="Uncaught Exception"
                )

    def main(
        self,
        session: ocs_agent.OpSession,
        params: Optional[Dict[str, Any]] = None,  # pylint: disable=unused-argument
    ) -> OcsOpReturnType:
        """
        **Process** - Main process for the Lakeshore240 agent.
        Gets temperature data at specified sample rate, and processes commands.
        """
        module: Optional[Module] = None
        session.set_status("running")

        # Clear pre-existing actions
        while not self.action_queue.empty():
            action = self.action_queue.get()
            action.resolve_action(False, return_message="Aborted by main process")

        exceptions_to_attempt_reconnect = (ConnectionError, TimeoutError)

        pm = Pacemaker(self.f_sample, quantize=False)
        while session.status in ["starting", "running"]:
            if module is None:
                # Try to instantiate module
                try:
                    module = Module(self.port)
                    log.info("Lakeshore initialized with ID: {sn}", sn=module.inst_sn)
                except exceptions_to_attempt_reconnect:
                    session.degraded = True
                    log.error(
                        "Could not connect to lakeshore:\n{exc}",
                        exc=traceback.format_exc(),
                    )
                    log.info("Retrying after 30 sec...")
                    time.sleep(30)
                    continue

            pm.sleep()
            try:
                self._get_and_pub_temp_data(module, session)
                self._process_actions(module)
                session.degraded = False
            except exceptions_to_attempt_reconnect:
                session.degraded = True
                log.error(
                    "Connection to lakeshore lost:\n{exc}",
                    exc=traceback.format_exc(),
                )
                module = None

        return True, "Ended main process"

    def _stop_main(self, session: ocs_agent.OpSession, params=None) -> OcsOpReturnType:  # pylint: disable=unused-argument
        session.set_status("stopping")
        return True, "Requesting to stop main process"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument(
        "--serial-number", type=str, help="Serial number of your Lakeshore240 device"
    )
    pgroup.add_argument("--port", type=str, help="Path to USB node for the lakeshore")
    pgroup.add_argument(
        "--mode",
        type=str,
        choices=["idle", "init", "acq"],
        help="Starting action for the agent.",
    )
    pgroup.add_argument(
        "--sampling-frequency",
        type=float,
        help="Sampling frequency for data acquisition",
    )

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))  # pylint: disable=E1101

    parser = make_parser()

    # Not used anymore, but we don't it to break the agent if these args are passed
    parser.add_argument("--fake-data", help=argparse.SUPPRESS)
    parser.add_argument("--num-channels", help=argparse.SUPPRESS)

    # Interpret options in the context of site_config.
    args = site_config.parse_args(
        agent_class="Lakeshore240Agent", parser=parser, args=args
    )

    if args.fake_data is not None:
        warnings.warn(
            "WARNING: the --fake-data parameter is deprecated, please "
            "remove from your site-config file",
            DeprecationWarning,
        )

    if args.num_channels is not None:
        warnings.warn(
            "WARNING: the --num-channels parameter is deprecated, please "
            "remove from your site-config file",
            DeprecationWarning,
        )

    if args.mode is not None:
        warnings.warn(
            "WARNING: the --init-mode parameter is deprecated, please "
            "remove from your site-config file",
            DeprecationWarning,
        )

    device_port = None
    if args.port is not None:
        device_port = args.port
    else:  # Tries to find correct USB port automatically
        # This exists if udev rules are setup properly for the 240s
        if os.path.exists("/dev/{}".format(args.serial_number)):
            device_port = "/dev/{}".format(args.serial_number)

        elif os.path.exists("/dev/serial/by-id"):
            ports = os.listdir("/dev/serial/by-id")
            for port in ports:
                if args.serial_number in port:
                    device_port = "/dev/serial/by-id/{}".format(port)
                    print("Found port {}".format(device_port))
                    break

    if device_port is None:
        print("Could not find device port for {}".format(args.serial_number))
        return

    agent, runner = ocs_agent.init_site_agent(args)

    kwargs = {"port": device_port}
    if args.sampling_frequency is not None:
        kwargs["f_sample"] = float(args.sampling_frequency)

    LS240_Agent(agent, **kwargs)
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
