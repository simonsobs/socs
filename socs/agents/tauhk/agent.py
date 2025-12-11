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


import os
import queue
import socket
import subprocess
import threading
import time
import re
import socket
from functools import lru_cache, partial, update_wrapper
import atexit
from subprocess import Popen
from datetime import datetime
from pb2.system_pb2 import HKdata, HKsystem
# The linter may tell you that these are unused but they are needed for the protobuf validation
from pb2 import validate_pb2, meta_pb2

from ocs import ocs_agent, site_config
import txaio


from protoc_gen_validate.validator import ValidationFailed, validate_all
from google.protobuf.json_format import MessageToDict


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

        self.command_port=("127.0.0.1", 3006)
        self.info_port = ("127.0.0.1", 3007)
        self.toplevel_messagae="system.HKsystem"

        self.latest_data = dict()

        self.process = None
        # ensure the crate daemon is stopped on exit
        atexit.register(self._stop_crate, None, None)

        agg_parameters = {
            'frame_length': 10 # seconds
        }
        self.agent.register_feed('tauhk_data', record=True, agg_params=agg_parameters, buffer_time=1.0)
        self.agent.register_feed('tauhk_logs', record=True, agg_params=agg_parameters, buffer_time=1.0)

    @ocs_agent.param('include_pattern', default=None, type=str)
    @ocs_agent.param('exclude_pattern', default=None, type=str)
    def receive_data(self, session, params):
        """receive_data(include_pattern=None, exclude_pattern=None)

        **Process** - Receive housekeeping data from tauHK and publish to OCS feed.

        Args:
            include_pattern (str, optional): Regex pattern to include specific data keys. Defaults to None.
            exclude_pattern (str, optional): Regex pattern to exclude specific data keys. Defaults to None
        
        Notes:
            session["data"] will contain the latest received data as a dictionary with flattened keys such as 'channelname_quantityname'.
            Typically quanitites of interest will be postfixed with _temperature.
        """

        # Insure there is no duplicate data acquisition processes
        if self._take_data:
            return False, 'Data acquisition is already running. Call stop to end the current acquisition.'

        include_pattern=re.compile(params['include_pattern']) if params['include_pattern'] else None
        exclude_pattern=re.compile(params['exclude_pattern']) if params['exclude_pattern'] else None
        
        
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
                    message = HKdata()
                    message.ParseFromString(data)
                    decoded_data = MessageToDict(message, preserving_proto_field_name=True)
                    
                    # Extract and convert the timestamp
                    message_timestamp = int(decoded_data["global_data"]["system_time"])/1000 #convert from millis from epoche to seconds
                    message_datetime = datetime.fromtimestamp(message_timestamp)

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
                        feed_message = {'block_name': f'tauhk_data_{spf}_spf', 'timestamp': message_timestamp,'data': data_dict}
                        self.agent.publish_to_feed('tauhk_data', feed_message)
                        # keep a running latest data dict
                        # here newer and older spfs may overwrite each other but 
                        # thats probably ok as it is the latest data after all
                        self.latest_data.update(data_dict)
                    # and make it available in the session
                    session.data = self.latest_data
                except Exception as e:
                    # raise e
                    #how best to handle an error here?
                    self.log.error(f"Error receiving data: {e}")

        self.agent.feeds['tauhk_data'].flush_buffer()

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
        """

        # Insure there is no duplicate crate processes
        # This is hardware - there is only the one...
        if self.process is not None:
            if self.process.poll() is None:
                return False, 'tauHK crate daemon is already running.'
            else:
                return False, 'tauHK crate daemon stopped unexpectedly, call stop to cleanup'

        # Call the crate interface binary
        self.process = subprocess.Popen(['./tauhk-agent'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={"RUST_LOG":"info"})
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
        while True:
            try:
                name, line = q.get(timeout=1.0)
                feed_message = {'block_name': f'tauhk_logs_{name}', 'timestamp': time.time(),'data': {f'tauhk_logs_{name}': line}}
                self.agent.publish_to_feed('tauhk_logs', feed_message)
            except queue.Empty:
                # When exiting cleanly the process will be None
                if self.process is None:
                    retval = (True, 'tauHK crate daemon stopped by user.')
                    break
                # When it crashes it will be not None but have a return code
                if self.process.poll() is not None:
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
    def generic_send(self, session, params, channel_name=None, option_name=None):
        """channelname_optionname(value=str)
        **Task** - Send a command for a specific channel and option to tauHK.

        Args:
            value (str): The value to set for the specified channel and option.
        
        Notes:
            This function has been dynamically registered for each channel and option using functools.partial.
            Refer to the task name for the specific channel and option being set.

            rtd_logdac sets the excitation range for RTDs from 0(min) to 15(max)
            rtd_uvolts sets the excitation voltage in microvolts (e.g., 56 for 56uV)
            diode_excitation sets the excitation mode for diodes: 0=DC, 1=AC, 2=None
            heater_mvolts sets the heater voltage in millivolts (e.g., 500 for 500mV)
            heater_percent sets the heater power as a percentage (0-100) of input voltage.
        """
        try:
            val = params['value']
        except KeyError:
            return False, 'No value provided in parameters.'
        
        # instantiate a message proto
        message = HKsystem()
        # get the type of the option we are setting
        thing_type = type(getattr(getattr(message, channel_name), option_name))
        value = thing_type()
        #deal with special bool case
        if thing_type == bool:
            if val.lower() in ['true', '1', 'yes']:
                value = True
            elif val.lower() in ['false', '0', 'no']:
                value = False
            else:
                return False, f"Invalid boolean value: {val} for {channel_name}.{option_name}"
        else:
            #try the generic type cast
            try:
                value = thing_type(val)
            except Exception as e:
                return False, f"Failed type cast for: {val} for {channel_name}.{option_name} due to {e}"
        try:
            # set the value in the message
            ## TODO: this likely fails on an empty message. Need to use setinparent for that special case
            setattr(getattr(message, channel_name), option_name, value)
        except Exception as e:
            return False, f"Failed to set {channel_name}.{option_name} to {value}: {e}"
        
        # validate the message
        try:
            validate_all(message)
        except Exception as e:
            return False, f"Validation failed for {channel_name}.{option_name} with value {value}: {e}"
    
        # and send it off
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(message.SerializeToString(), self.command_port)
        except Exception as e:
            return False, f"Failed to send message to tauHK: {e}"
            
        self.log.info(f'Sent the following message to tauHK: {message}')
        return True, f'Sent command to set {channel_name}.{option_name} to {value}.'
        
@lru_cache(maxsize=256)
def get_spf(channel_name, channel_quantity):
    '''
    Docstring for get_spf
    
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
        spf=80

    if spf is None:
        raise ValueError(f"No spf found for field {channel_name}.{channel_quantity}")

    return spf


def main(args = None):

    txaio.use_twisted()
    LOG = txaio.make_logger()

    txaio.start_logging(level= os.environ.get('LOGLEVEL', 'info'))

    args = site_config.parse_args(agent_class='TauHKAgent', args=args)
    agent, runner = ocs_agent.init_site_agent(args)

    #instantiate the system
    system = TauHKAgent(agent)
    
    #dynamically register the commands present in the protobuf
    message = HKsystem()
    #this grabs the names of all the channels (+ global_options)
    all_fields = message.DESCRIPTOR.fields_by_name.keys()
    for field in all_fields:
        #similarly this grabs all the options for each channel
        options = getattr(message, field).DESCRIPTOR.fields_by_name.keys()
        for option in options:
            #we skip raw as its not user friendly
            if option == 'raw':
                continue
            # register as channelname_optionname by partially prefilling the generic_send method
            task_func = partial(system.generic_send, channel_name=field, option_name=option)
            #copy over the docstring
            update_wrapper(task_func, system.generic_send)
            # agent.register_task(f'{field}_{option}', task_func)
    
    #register the data receiving process
    agent.register_process('receive_data', system.receive_data, system._stop_receive)

    #register the crate start/stop commands
    agent.register_process('start_crate', system.start_crate, system._stop_crate)
    
    #and start!
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
