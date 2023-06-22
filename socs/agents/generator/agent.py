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


def twos(val, bytes):
    """Take an unsigned integer representation of a two's compilment integer
    and return the correctly signed integer"""
    b = val.to_bytes(bytes, byteorder=byteorder, signed=False)
    return int.from_bytes(b, byteorder=byteorder, signed=True)


def interp_unsigned_double_reg(r1, r2):
    """Take two 16 bit register values and combine them assuming we really
    wanted to read a 32 bit unsigned register"""
    return (r1 << 16) + r2


def interp_signed_double_reg(r1, r2):
    """Take two 16 bit register values and combine them assuming we really
    wanted to read a 32 bit signed register"""
    return twos(interp_unsigned_double_reg(r1, r2), 4)


class ReadString(object):

    def __init__(self, config, error_out_of_range=True):
        self.name = config['string_name']
        self.read_start = config['read_start']
        self.read_len = config['read_len']
        self.functions = []
        self.rconfig = config['registers']
        self.error_val = -1
        self.error_out_of_range = error_out_of_range
        for i in self.rconfig:
            self.functions.append(self.build_reader_function(i, self.rconfig[i]))

    def build_reader_function(self, offset, rconfig):
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
        else:
            def evaluator(registers):
                return self.error_val

        def process(registers):
            val = evaluator(registers)
            if 'scale' in rconfig:
                val = val * rconfig['scale']

            if self.error_out_of_range:
                try:
                    if val < rconfig['min_va']:
                        val = self.error_val
                except KeyError:
                    pass

                try:
                    if val > rconfig['max_val']:
                        val = self.error_val
                except KeyError:
                    pass

            return {rconfig['name'].replace(' ', '_'): {'value': val, 'units': rconfig['units']}}

        return process

    def read(self, client):
        regdata = client.read_holding_registers(self.read_start, self.read_len)
        regs = regdata
        return_data = {}
        try:
            for i in range(self.read_len):
                return_data.update(self.functions[i](regs))
        except Exception as e:
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

    Attributes
    ----------
    read_strings : list
        Strings of registers defined in config to read from
    client : ModbusClient
        ModbusClient object that initializes connection
    """

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.read_strings = []

        self._build_config()

        self.client = ModbusClient(self.host, self.port, auto_open=True, auto_close=False)
        self.client.open()

    def _build_config(self):
        read_config = os.path.join(os.path.dirname(__file__), "config.yaml")
        with open(read_config) as f:
            data = yaml.load(f, Loader=yaml.SafeLoader)
        for string in [data]:
            self.read_strings.append(ReadString(string))

    def read_cycle(self):
        for i, val in enumerate(self.read_strings):
            data = self._read_regs(val)
            return data

    def _read_regs(self, register_string_obj):
        try:
            data = register_string_obj.read(self.client)
        except Exception as e:
            print('error in read', e)
            return

        return data


class GeneratorAgent:
    """Monitor the Generator controller via ModBus.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    host : str
        Address of the generator controller.
    port : int
        Port to generator controller, default to 5021.

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

    def __init__(self, agent, host='localhost', port=5021):

        self.host = host
        self.port = port

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

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

        self.generator = Generator(self.host, self.port)
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

            session.set_status('starting')

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

        Refer to the config file at `socs/agents/generator/config.yaml`_
        for all possible fields and their respective min/max values and units.
        Note: -1 will be returned for readings out of range.

        .. _socs/agents/generator/config.yaml: https://github.com/simonsobs/socs/blob/main/socs/agents/generator/config.yaml

        """

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            session.data = {"fields": {}}

            pm = Pacemaker(1, quantize=True)
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
                            field_dict = {reg: regdata[reg]}
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

                self.agent.publish_to_feed('generator', data)

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
                       host=args.host,
                       port=int(args.port))

    agent.register_task('init_generator', p.init_generator,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
