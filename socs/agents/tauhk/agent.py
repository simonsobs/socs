'''
protoc --python_out=pb2/ -I../protos -I../protos/include ../protos/system.proto ../protos/include/hk.proto ../protos/include/validate.proto ../protos/include/meta.proto

the import in the generated tauhk file is wrong
to fix it, change the import in the generated file from:
import blah as blah
to:
from . import blah as blah

pb2/include/hk_pb2.py will need to be adjusted as follows:
from .. import meta_pb2 as meta__pb2
from google.protobuf import empty_pb2 as google_dot_protobuf_dot_empty__pb2
from .. import validate_pb2 as validate__pb2
from google.protobuf import descriptor_pb2 as google_dot_protobuf_dot_descriptor__pb2

from ..meta_pb2 import *

'''


import atexit
import os
import pathlib
import queue
import re
import socket
import subprocess
import threading
import time
from copy import deepcopy
from datetime import datetime
from functools import lru_cache, partial

import txaio
import yaml
from google.protobuf.json_format import MessageToDict
from ocs import ocs_agent, ocs_feed, site_config
# The linter may tell you that these are unused but they are needed for the protobuf validation
# The linter may tell you that these are unused but they are needed for the protobuf validation
from pb2 import meta_pb2, validate_pb2
from pb2.system_pb2 import HKdata, HKsystem
from protoc_gen_validate.validator import ValidationFailed, validate_all


class TauHKAgent:
    """TauHKAgent handles communication with the tauHK housekeeping system.

    This agent acts as a bridge between the tauHK system and the OCS framework.
    For support please contact: simont@princeton.edu

    Notes:
        This agent relies on protobuf definitions that contain the experiment configurations.
    """

    def __init__(self, agent):
        self.agent = agent
        self.log = agent.log
        self._take_data = False

        self.command_port = ("127.0.0.1", 3006)
        self.info_port = ("127.0.0.1", 3007)
        self.toplevel_messagae = "system.HKsystem"

        self.latest_data = dict()
        self.averaged_data = dict()

        self.process = None
        # ensure the crate daemon is stopped on exit
        atexit.register(self._stop_crate, None, None)

        self.agent.register_feed('tauhk_data_full', record=True, agg_params={'frame_length': 10, 'exclude_influx': True, }, buffer_time=1.0)
        self.agent.register_feed('tauhk_data_influx', record=True, agg_params={'frame_length': 10, }, buffer_time=1.0)
        self.agent.register_feed('tauhk_logs', record=True, agg_params={'frame_length': 10}, buffer_time=1.0)

    @ocs_agent.param('include_pattern', default='(.*_temperature$)|(.*_voltage$)|(.*_resistance$)|(.*_logdac$)|(.*_enabled_dc$)|(.*_enabled_chop$)', type=str)
    @ocs_agent.param('exclude_pattern', default=None, type=str)
    def receive_data(self, session, params):
        """receive_data(include_pattern='(.*_temperature$)|(.*_voltage$)|(.*_resistance$)|(.*_logdac$)|(.*_enabled_dc$)|(.*_enabled_chop$)', exclude_pattern=None)

        **Process** - Receive housekeeping data from tauHK and publish to OCS feed.

        Args:
            include_pattern (str, optional): Regex pattern to include specific data keys.
                Defaults to save temperature, resistance, voltage, lodac, enabled_dc, and enabled_chop
            exclude_pattern (str, optional): Regex pattern to exclude specific data keys. Defaults to None

        Notes:
            session["data"] will contain the latest received data as a dictionary with flattened keys such as 'channelname_quantityname'.
            Typically quanitites of interest will be postfixed with _temperature.
            There will also be a timestamp field but this time corresponds to the latest update and some fields may not be updated at every timestamp.
        """

        # Insure there is no duplicate data acquisition processes
        if self._take_data:
            return False, 'Data acquisition is already running. Call stop to end the current acquisition.'

        include_pattern = re.compile(params['include_pattern']) if params['include_pattern'] else None
        exclude_pattern = re.compile(params['exclude_pattern']) if params['exclude_pattern'] else None

        self.log.info("Opening port and listening on UDP port 8080...")

        # Create UDP socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('localhost', 8080))
            sock.settimeout(1.0)  # Set a timeout for the socket operations
            # Aquire the "lock" ofc this is loosly unsafe so unlikely to get unlucky
            self._take_data = True
            while self._take_data:
                # generic try except to avoid breaking the loop.
                try:
                    data, addr = sock.recvfrom(4096)
                    # Decode protobuf to a nested dictionary
                    # print("got data")
                    message = HKdata()
                    message.ParseFromString(data)
                    decoded_data = MessageToDict(message, preserving_proto_field_name=True)

                    # Extract and convert the timestamp
                    message_timestamp = int(decoded_data["global_data"]["system_time"]) / 1000  # convert from millis from epoche to seconds

                    # The returned dict is nested with each channel containing its own dict of quantities
                    # This is inconvenient for OCS, so we flatten it out to key:value pairs with keys like channelname_quantityname
                    # However for data reasons we may want to filter which keys are included based on regex patterns
                    # Finally data blocks need to always have the same data in them so we separate the data into different SPF blocks based on the spf metadata in the protobuf
                    # hence data_dicts is a dict of spf:{key:value} where key is channelname_quantityname and value is the measurement
                    data_dicts = {}
                    for channel_name, channel_data in decoded_data.items():
                        for channel_quantity, value in channel_data.items():
                            # Create the flattened key
                            key = "_".join([channel_name, channel_quantity])

                            # Apply include and exclude filters
                            # is this logic right? Maybe include should override exclude?
                            if include_pattern and not include_pattern.search(key):
                                continue  # Skip if the key doesn't match the include pattern
                            if exclude_pattern and exclude_pattern.search(key):
                                continue  # Skip if the key matches the exclude pattern

                            # Determine the SPF for this key
                            spf = get_spf(channel_name, channel_quantity)

                            # Initialize the dict for this SPF if it doesn't exist
                            if spf not in data_dicts:
                                data_dicts[spf] = {}

                            data_dicts[spf][key] = value

                    # Since a single block needs to always have the same keys we split it into different
                    # sample rates (spf)
                    # So output one feed message per spf
                    for spf, data_dict in data_dicts.items():
                        feed_message = {'block_name': f'tauhk_data_{spf}_spf', 'timestamp': message_timestamp, 'data': data_dict}
                        # print("sent data")
                        self.agent.publish_to_feed('tauhk_data_full', feed_message)
                        # keep a running latest data dict
                        # here newer and older spfs may overwrite each other but
                        # thats probably ok as it is the latest data after all
                        self.latest_data.update(data_dict)
                        if spf not in self.averaged_data:
                            self.averaged_data[spf] = data_dict
                        else:
                            for measurement, value in data_dict.items():
                                self.averaged_data[spf][measurement] += value
                    # and make it available in the session
                    session.data = self.latest_data
                    session.data['timestamp'] = message_timestamp

                    # if we hit the 1 spf data (happens about every second)
                    # we publish to the influx database
                    if 1 in data_dicts:
                        data_averaged = dict()
                        for spf, data_dict in self.averaged_data.items():
                            for measurement, value in data_dict.items():
                                # average but keep the data type!
                                value_type = type(value)
                                data_averaged[measurement] = value_type(value / spf)

                        average_message = {'block_name': 'tauhk_data_averaged', 'timestamp': message_timestamp, 'data': data_averaged}
                        self.agent.publish_to_feed('tauhk_data_influx', average_message)
                        self.averaged_data = dict()
                except Exception as e:
                    # raise e
                    # how best to handle an error here?
                    self.log.error(f"Error receiving data: {e}")

        self.agent.feeds['tauhk_data_influx'].flush_buffer()
        self.agent.feeds['tauhk_data_full'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_receive(self, session, params):
        """_stop_receive()

        Stops the receive_data process.
        """
        if self._take_data:
            self._take_data = False
            return True, 'Stopping data acquisition request.'
        return True, 'Data acquisition was not running.'

    def start_crate(self, session, params):
        """Connect to tauHK crate

        **Process** - Runs the daemon that talks to the tauHK hardware.

        Notes:
            This process will start the tauHK crate daemon and listen for log messages from it.
            The logs will be published to the tauhk_logs feed and placed in session['data']['latest_log'].
            TODO: There is currently a bug with stderr buffering and logs arriving out of order
        """

        # Insure there is no duplicate crate processes
        # This is hardware - there is only the one...
        if self.process is not None:
            if self.process.poll() is None:
                return False, 'tauHK crate daemon is already running.'
            else:
                return False, 'tauHK crate daemon stopped unexpectedly, call stop to cleanup'

        # Call the crate interface binary
        # There are problems with buffering and logs arriving out of order
        agent_path = pathlib.Path(__file__).parent.resolve()
        self.process = subprocess.Popen(
            ['./tauhk-agent'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={
                "RUST_LOG": "info",
                "TAUHK_IP_CMD_SEND": "10.1.0.74",
                "TAUHK_IP_CMD_RECV": "10.1.0.77",
                "TAUHK_IP_DATA": "10.1.0.77"
            },
            bufsize=1,
            cwd=agent_path,
        )
        self.log.info(f"Started tauHK crate daemon with PID {self.process.pid}")

        # Create a function that listens to the stdout and stderr streams and sends one line at a time
        # Use a queue here since the self.agent.publish_to_feed is not thread safe
        def send_from_stream(stream, name='', q=None):
            for line in iter(stream.readline, ''):
                q.put((name, line.strip()))
            self.log.info(f"{name} stream ended")

        q = queue.Queue()
        # Non daemon threads since otherwise they end abruptly when the main thread ends and cause a segault on the .put
        threading.Thread(target=partial(send_from_stream, name='stdout', q=q), args=(self.process.stdout,), daemon=False).start()
        threading.Thread(target=partial(send_from_stream, name='stderr', q=q), args=(self.process.stderr,), daemon=False).start()

        # the main thread hangs out here sending log lines to the feed
        # If it's been a while between messages it can check if the process is still alive
        retval = None
        session.data = {'is_alive': True}
        while True:
            try:
                name, line = q.get(timeout=1.0)
                feed_message = {'block_name': f'tauhk_logs_{name}', 'timestamp': time.time(), 'data': {f'tauhk_logs_{name}': line}}
                session.data = {'latest_log': line, 'timestamp': time.time(), "is_alive": True}
                # self.log.info(str(line))
                self.agent.publish_to_feed('tauhk_logs', feed_message)
            except queue.Empty:
                # When exiting cleanly the process will be None
                if self.process is None:
                    session.data["is_alive"] = False
                    retval = (True, 'tauHK crate daemon stopped by user.')
                    break
                # When it crashes it will be not None but have a return code
                if self.process.poll() is not None:
                    session.data["is_alive"] = False
                    retval = (False, 'tauHK crate daemon stopped unexpectedly.')
                    break

        self.agent.feeds['tauhk_logs'].flush_buffer()
        return retval

    def _stop_crate(self, session, params):
        """_stop_crate()

        Stops the tauHK crate daemon.
        """
        if self.process is None:
            return True, 'tauHK crate daemon was not running.'
        if self.process.poll() is not None:
            return True, 'tauHK crate daemon stopped unexpectedly.'
        self.process.terminate()
        self.process.wait()
        self.process = None
        return True, 'tauHK crate daemon stopped.'

    @ocs_agent.param('value', type=str)
    @ocs_agent.param('option', type=str)
    @ocs_agent.param('channel', type=str)
    def generic_send(self, session, params):
        """generic_send(channel=str, option=str, value=str)
        **Task** - Send a command for a specific channel and option to tauHK.

        Args:
            channel (str): The name of the channel to which the command is sent.
            option (str): The name of the option within the channel to which the command is
            value (str): The value to set for the specified channel and option.

        Notes:
            Channels defintions are in the config file for tauHK.
            Different channel types have different options.
            A list of valid channel names and options is provided by the advertise task.

            In case you are writing a script, the following commands are available:
            rtdChannel.logdac sets the excitation range for RTDs from 0(min) to 15(max)
            rtdChannel.uvolts sets the excitation voltage in microvolts (e.g., 56 for 56uV)
            diodeChannel.excitation sets the excitation mode for diodes: 0=DC, 1=AC, 2=None
        """
        val = params['value']
        channel_name = params['channel']
        option_name = params['option']
        # instantiate a message proto
        message = HKsystem()

        ret, status = set_param(message, channel_name, option_name, val)
        if not ret:
            return False, status

        ret, status = send_command(message, self.command_port)
        if not ret:
            return False, status

        return True, f"Sent {channel_name}.{option_name}={val} successfully."

    def advertise(self, session, params):
        """advertise()

        **Process** - Advertise available commands by filling session.data

        Notes:
            `Session.data['settables']` will contain a dictionary with the available commands and their types.
            This dictionary is structured as follows:
                `channelName:{optionName:optionType}`
                `OptionType` is a list containing the following:
                ```
                    ["int", (min, max)]                     for integer types
                    ["enum", {"label_1": 0, "label_2": 1}]  for enum types
                    list()                                  for commands without parameters
                ```
            An example of a valid session.data is:
            ```
            {
                'global_options': {
                    'restart': list()                       # Restart the firmware running on the crate
                },
                'rtd_0': {
                    'logdac': ["int", (0, 15)],             # Set excitation in logdac units (more is more)
                    'uvolts': ["int", (0, 1000)]            # Set excitation voltage in microvolts
                },
                'diode_0': {
                    'excitation': ["enum", {                # Set excitation mode for diodes
                        'DC': 0,
                        'AC': 1,
                        'None': 2
                    }]
                },
            }
            ```
        """
        advertised = dict()

        # Restricted type mapping from the TYPE_* constants that FieldDescriptor.type returns
        type_mapping = {14: "enum", 13: "uint32", }

        # Grab the protobuf message definition as it contains the channel names and options
        message = HKsystem()
        # this grabs the names of all the channels (+ global_options)
        all_fields = message.DESCRIPTOR.fields_by_name.keys()
        for field in all_fields:
            advertised[field] = dict()
            # similarly this grabs all the commandable options for each channel
            options = getattr(message, field).DESCRIPTOR.fields_by_name.keys()
            for option in options:
                if option == 'raw':
                    # we skip raw as its not user friendly
                    continue
                if option == 'restart':
                    # special case for restart this is the empaty message
                    advertised[field][option] = list()
                    continue
                # generic case
                try:
                    data_type = type_mapping[getattr(message, field).DESCRIPTOR.fields_by_name[option].type]
                except KeyError:
                    # ugh oh not in my restricted mapping
                    self.log.error(f"Unknown type {getattr(message, field).DESCRIPTOR.fields_by_name[option].type} for {field}.{option}")
                    continue

                if data_type == "enum":
                    # we need to get the enum values
                    enum_dict = getattr(message, field).DESCRIPTOR.fields_by_name[option].enum_type.values_by_name
                    enum_dict = {k: v.number for k, v in enum_dict.items()}
                    advertised[field][option] = ["enum", enum_dict]
                elif data_type == "uint32":
                    # Lets check for validate rules
                    field_options = getattr(message, field).DESCRIPTOR.fields_by_name[option].GetOptions()
                    for field_option in field_options.ListFields():
                        found = False
                        if field_option[0].full_name == 'validate.rules':
                            found = True
                            rule = field_option[1]
                            max_val = rule.uint32.lte
                            min_val = rule.uint32.gte
                            advertised[field][option] = ["int", (min_val, max_val)]
                            break
                    if not found:
                        # no explicit rules so assume full range of uint32
                        advertised[field][option] = ["int", (0, 2**32 - 1)]
                else:
                    # Currently unimplemented
                    self.log.error(f"Unknown type {data_type} for {field}.{option}")
        session.data = {"settables": advertised}
        return True, 'Advertised tauHK commands.'

    @ocs_agent.param('config_file', type=str)
    def load_config(self, session, params):
        """load_config()

        **Task** - Send a config containing nominal excitations to tauHK.

        Args:
            config_file (str): The path to the configuration file in YAML format.

        Notes:
            The YAML configuration file should contain all the commands to be sent to tauHK.

            An example of a valid configuration file is:
            ```
            rtd_1:
                - logdac: 10
            rtd_2:
                - uvolts: 56
                - option: 42        # multiple options can be set for a channel
            diode_3:
                - excitation: 1     # 0=DC, 1=AC, 2=None enums not supported currently
            ```
        """
        if 'config_file' not in params:
            return False, 'No config file provided.'
        agent_path = pathlib.Path(__file__).parent.resolve()
        with open(os.path.join(agent_path, params['config_file']), 'r') as f:
            config = yaml.safe_load(f)

        message = HKsystem()
        for channel_name, channel_command in config.items():
            # key is channel name
            # value is a list of options
            # each element has key value pairs of option_name:option_value
            for command in channel_command:
                option, value = iter(command.items()).__next__()

                ret_val, ret_str = set_param(message, channel_name, option, value)
                if not ret_val:
                    return False, ret_str

        ret, status = send_command(message, self.command_port)
        if not ret:
            return False, status

        return True, f"Loaded config from {params['config_file']} successfully."


@lru_cache(maxsize=256)
def get_spf(channel_name, channel_quantity):
    '''get_spf(channel_name, channel_quantity)
    Return the samples per frame (spf) for a given channel and quantity as defined in the protobuf options.

    :param channel_name: Description
    :param channel_quantity: Description
    '''
    message = HKdata()
    field_options = getattr(message, channel_name).DESCRIPTOR.fields_by_name[channel_quantity].GetOptions()
    spf = None
    for field_option in field_options.ListFields():
        if field_option[0].name == 'spf':
            spf = field_option[1]
            break
    if channel_name == "global_data" and (channel_quantity == "system_time" or channel_quantity == "mcu_time"):
        spf = 80

    if spf is None:
        raise ValueError(f"No spf found for field {channel_name}.{channel_quantity}")

    return spf


def send_command(message, command_port):
    """send_command(message, command_port)
    Send a premade protobuf command to the tauHK system.

    :param message: Protobuf message to be sent
    :param command_port: The port on which to send it to
    """
    # and send it off
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(message.SerializeToString(), command_port)
    except Exception as e:
        return False, f"Failed to send message to tauHK: {e}"
    return True, 'Sent scuccessfully.'


def set_param(message, channel_name, option_name, val):
    """set_param(message, channel_name, option_name, val)
    Set a parameter in a premade protobuf command.

    :param message: Protobuf message to be modified
    :param channel_name: The name of the channel to which the command is sent.
    :param option_name: The name of the option within the channel to which the command is sent.
    :param val: The value to set for the specified channel and option.
    """
    # get the type of the option we are setting
    thing_type = type(getattr(getattr(message, channel_name), option_name))
    value = thing_type()
    # deal with special bool case
    if thing_type == bool:
        if val.lower() in ['true', '1', 'yes']:
            value = True
        elif val.lower() in ['false', '0', 'no']:
            value = False
        else:
            return False, f"Invalid boolean value: {val} for {channel_name}.{option_name}"
    else:
        # try the generic type cast
        try:
            value = thing_type(val)
        except Exception as e:
            return False, f"Failed type cast for: {val} for {channel_name}.{option_name} due to {e}"
    try:
        # set the value in the message
        # TODO: this likely fails on an empty message. Need to use setinparent for that special case
        setattr(getattr(message, channel_name), option_name, value)
    except Exception as e:
        return False, f"Failed to set {channel_name}.{option_name} to {value}: {e}"

    # validate the message
    try:
        validate_all(message)
    except Exception as e:
        return False, f"Validation failed for {channel_name}.{option_name} with value {value}: {e}"
    return True, f"Set {channel_name}.{option_name} to {value} successfully."


def main(args=None):

    txaio.use_twisted()
    LOG = txaio.make_logger()

    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    args = site_config.parse_args(agent_class='tauHKAgent', args=args)
    agent, runner = ocs_agent.init_site_agent(args)

    # instantiate the system
    system = TauHKAgent(agent)

    # register the generic send command config commands
    agent.register_task('generic_send', system.generic_send)
    agent.register_task('load_config', system.load_config)

    # register the advertise process and run it on startup.
    # The config is compiled in so it can never change and therefore it never needs tio be re-run
    def dummy_stop(*args, **kwargs):
        return True, "Advertise process does not support stopping."
    agent.register_process('advertise', system.advertise, stop_func=dummy_stop, startup=True)

    # register the data receiving process
    agent.register_process('receive_data', system.receive_data, system._stop_receive)

    # register the crate start/stop commands
    agent.register_process('start_crate', system.start_crate, system._stop_crate)

    # and start!
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
