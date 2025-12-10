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
import socket
import time
import re
import socket
from functools import partial, update_wrapper
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

        agg_parameters = {
            'frame_length': 10 # seconds
        }
        self.agent.register_feed('tauhk_data', record=True, agg_params=agg_parameters, buffer_time=1.0)

    @ocs_agent.param('include_pattern', default=None, type=str)
    @ocs_agent.param('exclude_pattern', default=None, type=str)
    def receive_data(self, session, params):
        """receive_data(include_pattern=None, exclude_pattern=None)

        **Process** - Receive housekeeping data from tauHK and publish to OCS feed.

        Args:
            include_pattern (str, optional): Regex pattern to include specific data keys. Defaults to None.
            exclude_pattern (str, optional): Regex pattern to exclude specific data keys. Defaults to None
        
        Notes:
        #THIS NOTE IS OUT OF DATE PLEASE FIX TODO:
            session["data"] will contain the latest received data as a dictionary with flattened keys such as 'channelname_quantityname'.
            Typically quanitites of interest will be postfixed with _temperature.
        """

        self.log.info("Opening port and listening on UDP port 8080...")

        include_pattern=re.compile(params['include_pattern']) if params['include_pattern'] else None
        exclude_pattern=re.compile(params['exclude_pattern']) if params['exclude_pattern'] else None
        
        # Create UDP socket
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(('localhost', 8080))
            self._take_data = True
            
            initialized_count = 0
            initial_dict = dict()

            while self._take_data:
                # generic try except to avoid breaking the loop.
                try:
                    data, addr = sock.recvfrom(4096)
                    # print(f"Received data from {addr}: {data}")
                    message = HKdata()
                    message.ParseFromString(data)
                    decoded_data = MessageToDict(message, preserving_proto_field_name=True)
                    # print(decoded_data)
                    message_timestamp = int(decoded_data["global_data"]["system_time"])/1000 #convert from millis from epoche to seconds
                    message_datetime = datetime.fromtimestamp(message_timestamp)
                    # print(f"Message timestamp: {message_datetime.isoformat()}")
                    # The returned dict is nested with each channel containing its own dict of quantities
                    # This is inconvenient for OCS, so we flatten it out to key:value pairs with keys like channelname_quantityname
                    # However for data reasons we may want to filter which keys are included based on regex patterns
                    data_dicts = {}
                    for channel_name, channel_data in decoded_data.items():
                        for channel_quantity, value in channel_data.items():
                            key = "_".join([channel_name, channel_quantity])
                            
                            field_options = getattr(message, channel_name).DESCRIPTOR.fields_by_name[channel_quantity].GetOptions()
                            spf = None
                            for field_option in field_options.ListFields():
                                if field_option[0].name == 'spf':
                                    spf = field_option[1]
                                    break
                            if key == "global_data_system_time" or key == "global_data_mcu_time":
                                spf=80

                            if spf is None:
                                raise ValueError(f"No spf found for field {key}")

                            if spf not in data_dicts:
                                data_dicts[spf] = {}

                            data_dicts[spf][key] = value
                    # print(f"Received data at {message_datetime.isoformat()}")
                        
                    # The data gets output to the feeds
                    for spf, data_dict in data_dicts.items():
                        feed_message = {'block_name': f'tauhk_data_{spf}_spf', 'timestamp': message_timestamp,'data': data_dict}
                        self.agent.publish_to_feed('tauhk_data', feed_message)
                except Exception as e:
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
        return False, 'Data acquisition was not running.'


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
            agent.register_task(f'{field}_{option}', task_func)
    
    #register the data receiving process
    agent.register_process('receive_data', system.receive_data, system._stop_receive)
    
    #and start!
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
