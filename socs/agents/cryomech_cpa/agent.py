# Script to log and readout PTC data through ethernet connection.
# Tamar Ervin and Jake Spisak, February 2019
# Sanah Bhimani, May 2022

import argparse
import random
import socket
import struct
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

STX = '\x02'
ADDR = '\x10'
CMD = '\x80'
CR = '\x0D'
DATA_WRITE = '\x61'
DATA_READ = '\x63'
ESC = '\x07'
ESC_STX = '\x30'
ESC_CR = '\x31'
ESC_ESC = '\x32'


class PTC:
    def __init__(self, ip_address, port=502, timeout=10, fake_errors=False):
        self.ip_address = ip_address
        self.port = int(port)
        self.fake_errors = fake_errors

        self.model = None
        self.serial = None
        self.software_revision = None

        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))  # connects to the PTC
        self.comm.settimeout(timeout)

    def get_data(self):
        """
        Gets the raw data from the ptc and returns it in a usable format.
        """
        self.comm.sendall(self.buildRegistersQuery())
        data = self.comm.recv(1024)
        data_flag, brd = self.breakdownReplyData(data)

        return data_flag, brd

    @staticmethod
    def buildRegistersQuery():
        query = bytes([0x09, 0x99,  # Message ID
                       0x00, 0x00,  # Unused
                       0x00, 0x06,  # Message size in bytes
                       0x01,        # Slave Address
                       0x04,        # Function Code
                       0x00, 0x01,   # The starting Register Number
                       0x00, 0x35])  # How many to read
        return query

    def power(self, state):
        """Turn the PTC on or off.

        Parameters
        ----------
        state : str
            Desired power state of the PTC, either 'on', or 'off'.

        """
        command = [0x09, 0x99,  # Message ID
                   0x00, 0x00,  # Unused
                   0x00, 0x06,  # Message size in bytes
                   0x01,        # Slave Address
                   0x06,        # Function Code
                   0x00, 0x01]   # Register Number

        if state.lower() == 'on':
            command.extend([0x00, 0x01])
        elif state.lower() == 'off':
            command.extend([0x00, 0xff])
        else:
            raise ValueError(f"Invalid state: {state}")

        self.comm.sendall(bytes(command))
        self.comm.recv(1024)  # Discard the echoed command

    def breakdownReplyData(self, rawdata):
        """Take in raw ptc data, and return a dictionary.

        The dictionary keys are the data labels, the dictionary values are the
        data in floats or ints.

        Returns
        -------
        data_flag : bool
            False if data is valid, True if output could not be interpretted.
        data : dict
            Data dictionary already formatted for passing to OCS Feed.

        """

        # Associations between keys and their location in rawData
        keyloc = {"Operating_State": [9, 10],
                  "Compressor_State": [11, 12],
                  "Warning_State": [15, 16, 13, 14],
                  "Alarm_State": [19, 20, 17, 18],
                  "Coolant_In_Temp": [23, 24, 21, 22],
                  "Coolant_Out_Temp": [27, 28, 25, 26],
                  "Oil_Temp": [31, 32, 29, 30],
                  "Helium_Temp": [35, 36, 33, 34],
                  "Low_Pressure": [39, 40, 37, 38],
                  "Low_Pressure_Average": [43, 44, 41, 42],
                  "High_Pressure": [47, 48, 45, 46],
                  "High_Pressure_Average": [51, 52, 49, 50],
                  "Delta_Pressure_Average": [55, 56, 53, 54],
                  "Motor_Current": [59, 60, 57, 58],
                  "Hours_of_Operation": [63, 64, 61, 62],
                  "Pressure_Unit": [65, 66],
                  "Temperature_Unit": [67, 68],
                  "Serial_Number": [69, 70],
                  "Model": [71, 72],
                  "Software_Revision": [73, 74]}

        # Iterate through all keys and return the data in a usable format.
        # If there is an error in the string format, print the
        # error to logs, return an empty dictionary, and flag the data as bad
        data = {}

        # If fake_errors=True, then randomly output the string 'FAKE ERROR'
        # instead of the actual data 50% of the time
        if self.fake_errors:
            if random.random() < 0.5:
                rawdata = "FAKE ERROR"

        try:
            for key in keyloc.keys():
                locs = keyloc[key]
                wkrBytes = bytes([rawdata[loc] for loc in locs])

                # four different data formats to unpack
                # Big endian unsigned integer 16 bits
                if key in [
                    "Operating_State",
                    "Compressor_State",
                    "Pressure_Unit",
                    "Temperature_Unit",
                    "Serial_Number",
                ]:
                    state = struct.unpack(">H", wkrBytes)[0]
                    # Serial number is an attribute, not publishable data
                    if key == "Serial_Number":
                        self.serial = state
                    else:
                        data[key] = state
                # 32bit signed integer which is actually stored as a
                # 32bit IEEE float (silly)
                elif key in ["Warning_State", "Alarm_State"]:
                    state = int(struct.unpack(">f", wkrBytes)[0])
                    data[key] = state
                # 2 x 8-bit lookup tables.
                elif key in ["Model"]:
                    model_major = struct.unpack(
                        ">B", bytes([rawdata[locs[0]]]))[0]
                    model_minor = struct.unpack(
                        ">B", bytes([rawdata[locs[1]]]))[0]
                    # Model is an attribute, not publishable data
                    self.model = str(model_major) + "_" + str(model_minor)
                elif key in ["Software_Revision"]:
                    version_major = struct.unpack(
                        ">B", bytes([rawdata[locs[0]]]))[0]
                    version_minor = struct.unpack(
                        ">B", bytes([rawdata[locs[1]]]))[0]
                    self.software_revision = str(version_major) + "." + str(version_minor)
                # 32 bit Big endian IEEE floating point
                else:
                    data[key] = struct.unpack(">f", wkrBytes)[0]

            data_flag = False

        except BaseException:
            data_flag = True
            print("Compressor output could not be converted to numbers."
                  f"Skipping this data block. Bad output string is {rawdata}")

        return data_flag, data

    def __del__(self):
        """
        If the PTC class instance is destroyed, close the connection to the
        ptc.
        """
        self.comm.close()


class PTCAgent:
    """Agent to connect to a single cryomech compressor.

    Parameters:
        port (int): TCP port to connect to.
        ip_address (str): IP Address for the compressor.
        f_sample (float, optional): Data acquisiton rate, defaults to 2.5 Hz.
        fake_errors (bool, optional): Generates fake errors in the string
            output 50% of the time.

    """

    def __init__(self, agent, port, ip_address, f_sample=2.5,
                 fake_errors=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.ip_address = ip_address
        self.fake_errors = fake_errors

        self.port = port
        self.module = None
        self.f_sample = f_sample

        self.initialized = False
        self.take_data = False

        # Registers data feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('ptc_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init(auto_acquire=False)

        **Task** - Initializes the connection to the PTC.

        Parameters:
            auto_acquire (bool): Automatically start acq process after
                initialization if True. Defaults to False.

        """
        if self.initialized:
            return True, "Already Initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            # Establish connection to ptc
            self.ptc = PTC(self.ip_address, port=self.port,
                           fake_errors=self.fake_errors)

            # Test connection and display identifying info
            self.ptc.get_data()
            print("PTC Model:", self.ptc.model)
            print("PTC Serial Number:", self.ptc.serial)
            print("Software Revision is:", self.ptc.software_revision)

        self.initialized = True

        # Start data acquisition if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "PTC agent initialized"

    @ocs_agent.param('state', type=str, choices=['off', 'on'])
    def power_ptc(self, session, params=None):
        """power_ptc(state=None)

        **Task** - Remotely turn the PTC on or off.

        Parameters
        ----------
        state : str
            Desired power state of the PTC, either 'on', or 'off'.

        """
        with self.lock.acquire_timeout(3, job='power_ptc') as acquired:
            if not acquired:
                self.log.warn("Could not start task because {} is already "
                              "running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.ptc.power(params['state'])

        return True, "PTC powered {}".format(params['state'])

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acqusition of data from the PTC.

        Parameters:
            test_mode (bool, optional): Run the Process loop only once.
                This is meant only for testing. Default is False.

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already"
                              "running".format(self.lock.job))
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True

            while self.take_data:
                # Relinquish sampling lock occasionally
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                # Publish data, waiting 1/f_sample seconds in between calls.
                pub_data = {'timestamp': time.time(),
                            'block_name': 'ptc_status'}
                data_flag, data = self.ptc.get_data()
                pub_data['data'] = data
                # If there is an error in compressor output (data_flag = True),
                # do not publish
                if not data_flag:
                    self.agent.publish_to_feed('ptc_status', pub_data)
                time.sleep(1. / self.f_sample)

                if params['test_mode']:
                    break

            self.agent.feeds["ptc_status"].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """Stops acqusition of data from the PTC."""
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--port', default=502)
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--mode', choices=['init', 'acq'])
    pgroup.add_argument('--fake-errors', default=False,
                        help="If True, randomly output 'FAKE ERROR' instead of "
                             "data half of the time.")

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='CryomechCPAAgent',
                                  parser=parser,
                                  args=args)
    print('I am in charge of device with serial number: %s' % args.serial_number)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    # Call launcher function (initiates connection to appropriate
    # WAMP hub and realm).

    agent, runner = ocs_agent.init_site_agent(args)

    # create agent instance and run log creation
    ptc = PTCAgent(agent, args.port, args.ip_address,
                   fake_errors=args.fake_errors)

    agent.register_task('init', ptc.init, startup=init_params)
    agent.register_process('acq', ptc.acq, ptc._stop_acq)
    agent.register_task('power_ptc', ptc.power_ptc)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
