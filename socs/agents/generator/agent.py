import argparse
import os
import sys
import time

import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from pyModbusTCP.client import ModbusClient

byteorder = sys.byteorder


def load_configs(dir_name, config_extension='yaml'):
    '''Loads all register configuration files form the specified directory (path).
    The configurations are returned as a list of the configurations from individual files.'''

    config_dir = os.environ.get('OCS_CONFIG_DIR')
    path = os.path.join(config_dir, 'generator_config', dir_name)

    all_configs = []

    ls = os.listdir(path)

    # Make a filter so that we only try to load files ending in config_extension
    def filt(f_name):
        return f_name.endswith(config_extension)
    # Filter
    configs = filter(filt, ls)
    # Load configurations from the remaining files
    for f in configs:
        read_config = os.path.join(path, f)
        with open(read_config) as f:
            try:
                data = yaml.load(f, Loader=yaml.SafeLoader)
            except BaseException:
                pass
            all_configs.append(data)
    return all_configs


def twos(val, bytes):
    '''Take an unsigned integer representation of a two's compilment integer and return the correctly signed integer'''
    b = val.to_bytes(bytes, byteorder=byteorder, signed=False)
    return int.from_bytes(b, byteorder=byteorder, signed=True)


def interp_unsigned_double_reg(r1, r2):
    '''Take two 16 bit register values and combine them assuming we really wanted to read a 32 bit unsigned register'''
    return (r1 << 16) + r2


def interp_signed_double_reg(r1, r2):
    '''Take two 16 bit register values and combine them assuming we really wanted to read a 32 bit signed register'''
    return twos(interp_unsigned_double_reg(r1, r2), 4)


def make_bin_reader(offset, spec):
    '''Read an individual bit or continuous range of bits out of the 2 byte register.
    A single bit can be specified as a single number between 1 and 16, and a range can
    be specified with a dash, i.e. X-Y where both X and Y are in the range
    1 to 16 and X < Y. In either case the bit or range of bits will be returned as an
    integer.'''
    spec = spec.split(' ')[1:]
    spec = spec[0].split('-')
    spec = [int(s) for s in spec]
    if len(spec) == 1:
        # Process individual bit
        spec = spec[0]
        # The mask leaves only the desired bit
        mask = sum([1 << s for s in range(spec - 1, spec)])

        def reader(val):
            return (val[offset] & mask) >> spec - 1
        return reader
    elif len(spec) == 2:
        # Process range
        low = spec[0]
        high = spec[1]
        if low >= high:
            raise ValueError('First bit in range specification must be smaller than last.')
        # The mask leaves only the desired bits
        mask = sum([1 << s for s in range(low - 1, high)])

        def reader(val):
            return (val[offset] & mask) >> low - 1
        return reader
    else:
        raise ValueError('Cannot read binary read_as specification; use single bit or continuous range.')


class ReadBlock(object):
    '''An object for reading, converting, and evaluating information from a single contiouous block of registers'''

    def __init__(self, config, error_out_of_range=True, filter_errors=True):
        self.name = config['block_name']

        try:
            self.read_start = config['read_start']
        except KeyError:
            self.read_start = config['page'] * 256

        self.read_len = config['read_len']
        self.functions = []
        self.rconfig = config['registers']
        self.error_val = None
        self.error_out_of_range = error_out_of_range
        self.filter_errors = filter_errors
        for i in self.rconfig:
            self.functions.append(self.build_reader_function(i, self.rconfig[i]))

    def build_reader_function(self, name, rconfig):
        '''Build and return a closure around a function that converts a specified piece of information from the block'''
        offset = rconfig['offset']

        if rconfig['read_as'] == '16U':
            def evaluator(registers):
                return registers[offset]
        elif rconfig['read_as'] == '16S':
            def evaluator(registers):
                return twos(registers[offset], 2)
        elif rconfig['read_as'] == '32U':
            def evaluator(registers):
                return interp_unsigned_double_reg(registers[offset], registers[offset + 1])
        elif rconfig['read_as'] == '32S':
            def evaluator(registers):
                return interp_signed_double_reg(registers[offset], registers[offset + 1])
        elif 'bin' in rconfig['read_as']:
            evaluator = make_bin_reader(offset, rconfig['read_as'])
        else:
            def evaluator(registers):
                return self.error_val

        def process(registers):
            val = evaluator(registers)
            if 'scale' in rconfig:
                val = val * rconfig['scale']

            if self.error_out_of_range:
                try:
                    if val < rconfig['min_val']:
                        val = self.error_val
                except KeyError:
                    pass

                try:
                    if val > rconfig['max_val']:
                        val = self.error_val
                except KeyError:
                    pass

            if val != self.error_val or not self.filter_errors:
                return {name: {'value': float(val), 'units': rconfig['units']}}
            else:
                return None

        return process

    def read(self, client):
        # Perform the read for the entire block
        registers = client.read_holding_registers(self.read_start, self.read_len)
        return_data = {}
        try:
            # Iterate through the functions that convert and return the individual pieces of
            # data from this block
            for f in self.functions:
                this_data = f(registers)
                if this_data is not None:
                    return_data.update(this_data)
        except Exception as e:
            # print(registers)
            print(f'Error in processing data: {e}')

        return return_data


class Generator:
    """Functions to communite with the Generator controller

    Parameters
    ----------
    host : str
        Address of the generator controller.
    port : int
        Port to generator controller, default to 5021.
    config_dir : string
        Sub-directory of .yaml configuration files that specify blocks of registers to read
        and specifies how to convert them into useable data.
    block_space_time : float
        Amount of time (in seconds) to wait between issuing seperate read_multiple_registers
        commands to the device. DSE device appears to crash without this waiting period.
    close_port : boolean
       Whether or not to close the open port to the device while waiting for the next Pacemaker
       triggered read cycle. The idea here is that closing the port alllows DSEWebNet to function
       in parallel with the agent.

    Attributes
    ----------
    read_blocks : list
        List of ReadBlock objects that represent the different continuous register locations to
        read from as specified in the config files.
    client : ModbusClient
        ModbusClient object that initializes connection
    """

    def __init__(self, host, port, config_dir, block_space_time=.1, close_port=True):
        self.host = host
        self.port = port
        self.read_config = load_configs(config_dir)
        self._build_config()
        self.close_port = close_port
        self.block_space_time = block_space_time
        self.client = ModbusClient(self.host, self.port, auto_open=True, auto_close=False)
        self.client.open()

    def _build_config(self):
        self.read_blocks = []
        for block in self.read_config:
            self.read_blocks.append(ReadBlock(block))

    def read_cycle(self):
        this_cycle_data = {}
        for i, val in enumerate(self.read_blocks):
            data = self._read_regs(val)
            this_cycle_data.update(data)
            time.sleep(self.block_space_time)  # A gap in time is required between individual requests,
            # i.e. a pause between reading each read_multiple_registers command.
        return this_cycle_data

    def _read_regs(self, register_block_object):
        if self.close_port:
            self.client.open()
        try:
            data = register_block_object.read(self.client)
        except Exception as e:
            print('error in read', e)
            if self.close_port:
                self.client.open()
            return
        if self.close_port:
            self.client.open()
        return data


class GeneratorAgent:
    """Monitor the Generator controller via ModBus.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    configdir : str
        Directory where .yaml configuration files specific to this generator instance
        are stored.
    host : str
        Address of the generator controller.
    port : int
        Port to generator controller, default to 5021.
    sample_interval : float
        Time between samples in seconds.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    take_data : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the ibootbar. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, configdir, host='localhost', port=5021, sample_interval=10.):

        self.host = host
        self.port = port

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.configdir = configdir

        self.pacemaker_freq = 1. / sample_interval

        self.initialized = False
        self.take_data = False

        self.generator = None

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('generator',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def _connect(self):
        """connect()
        Instantiates Generator object and check if client is open
        """

        self.generator = Generator(self.host, self.port, config_dir=self.configdir)
        if self.generator.client.is_open:
            self.initialized = True
        else:
            self.initialized = False

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_generator(self, session, params=None):
        """init_generator(auto_acquire=False)

        **Task** - Perform first time setup of the Generator.

        Parameters:
            auto_acquire (bool, optional): Starts data acquisition after
                initialization if True. Defaults to False.

        """

        if self.initialized:
            return True, "Already initialized."

        with self.lock.acquire_timeout(3, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self._connect()
            if not self.initialized:
                return False, 'Could not connect to generator'

        # Start data acquisition if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Generator initialized.'

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()

        **Process** - Start data acquisition.

        Notes
        -----
        The most recent data collected is stored in session data in the
        structure::

            >>> response.session['data']
            {"fields":
                {'Oil_pressure': {'value': 100.0, 'units': 'Kpa'},
                 'Coolant_temperature': {'value': 20.0, 'units': 'Degrees C'},
                 'Oil_temperature': {'value': 20.0, 'units': 'Degrees C'},
                 'Fuel_level': {'value': 100.0, 'units': '%'},
                 'Charge_alternator_voltage': {'value': 10.0, 'units': 'V'},
                 'Engine_Battery_voltage': {'value': 10.0, 'units': 'V'},
                 'Engine_speed': {'value': 4000, 'units': 'RPM'},
                 'Generator_frequency': {'value': 1.0, 'units': 'Hz'},
                 ...
                 'connection': {'last_attempt': 1680812613.939653, 'connected': True}},
             "address": 'localhost',
             "timestamp":1601925677.6914878}


        """

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            self.take_data = True

            session.data = {"fields": {}}

            pm = Pacemaker(self.pacemaker_freq)
            while self.take_data:
                pm.sleep()

                current_time = time.time()
                data = {
                    'timestamp': current_time,
                    'connection': {},
                    'block_name': 'registers',
                    'data': {}
                }
                if not self.generator.client.is_open:
                    self.initialized = False

                # Try to re-initialize if connection lost
                if not self.initialized:
                    self._connect()

                # Only get readings if connected
                if self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': True}})
                    session.data['address'] = self.host

                    regdata = self.generator.read_cycle()
                    if regdata:
                        for reg in regdata:
                            data['data'][reg] = regdata[reg]["value"]
                            field_dict = {reg: regdata[reg]['value']}
                            session.data['fields'].update(field_dict)
                        session.data.update({'timestamp': current_time})
                    else:
                        self.log.info('Connection error or error in processing data.')
                        self.initialized = False

                # Continue trying to connect
                if not self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': False}})
                    self.log.info('Trying to reconnect.')
                    continue

                for field, val in data['data'].items():
                    _data = {
                        'timestamp': current_time,
                        'block_name': field,
                        'data': {field: val}
                    }
                    self.agent.publish_to_feed('generator', _data)

            self.agent.feeds['generator'].flush_buffer()

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
    pgroup.add_argument("--host", help="Address to listen to.")
    pgroup.add_argument("--port", default=5021,
                        help="Port to listen on.")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument("--configdir", type=str, help="Path to directory containing .yaml config files.")
    pgroup.add_argument("--sample-interval", type=float, default=10., help="Time between samples in seconds.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='GeneratorAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = GeneratorAgent(agent,
                       configdir=args.configdir,
                       host=args.host,
                       port=int(args.port),
                       sample_interval=args.sample_interval)

    agent.register_task('init_generator', p.init_generator,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
