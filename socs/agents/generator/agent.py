import argparse
import os
import sys
import time
import warnings
from typing import Optional

import txaio
import yaml
from pyModbusTCP.client import ModbusClient

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

byteorder = sys.byteorder


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
            def evaluator(registers): return registers[offset]
        elif rconfig['read_as'] == '16S':
            def evaluator(registers): return twos(registers[offset], 2)
        elif rconfig['read_as'] == '32U':
            def evaluator(registers): return interp_unsigned_double_reg(registers[offset], registers[offset + 1])
        elif rconfig['read_as'] == '32S':
            def evaluator(registers): return interp_signed_double_reg(registers[offset], registers[offset + 1])
        else:
            def evaluator(registers): return self.error_val

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


class GeneratorAgent:

    def __init__(self, agent, host='localhost', port=5021, read_config=None):

        self.host = host
        self.port = port
        self.read_strings = []

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        self.client = None

        if read_config is not None:
            with open(read_config) as f:
                data = yaml.load(f, Loader=yaml.FullLoader)
            self.build_config([data])
            self.log.info("Config file loaded successfully.")
        else:
            self.log.info("No config file provided.")

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('generator',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def build_config(self, config):
        for string in config:
            self.read_strings.append(ReadString(string))

    def read_cycle(self, client):
        for i, val in enumerate(self.read_strings):
            data = self.read_regs(client, val)
            return data

    def read_regs(self, client, register_string_obj):
        try:
            data = register_string_obj.read(client)
        except Exception as e:
            print('error in read', e)
            return

        return data

    def init_generator(self, session, params=None):
        """init_generator(auto_acquire=False)

        **Task** - Perform first time setup of the Generator.

        Parameters:
            auto_acquire (bool, optional): Starts data acquisition after
                initialization if True. Defaults to False.

        """
        if params is None:
            params = {}

        auto_acquire = params.get('auto_acquire', False)

        if self.initialized:
            return True, "Already initialized."

        with self.lock.acquire_timeout(3, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')

            client = ModbusClient(host=self.host, port=self.port, auto_open=True, auto_close=False)
            if client.open():
                self.client = client
                self.initialized = True
            else:
                self.initialized = False
                return False, 'Could not connect to generator'

        # Start data acquisition if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Generator initialized.'

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
             "timestamp":1601925677.6914878}

        Refer to the config file for all possible fields and their respective
        min/max values and units. Note: -1 will be returned for readings
        out of range.

        """
        if params is None:
            params = {}

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            session.data = {"fields": {}}

            while self.take_data:
                current_time = time.time()
                data = {
                    'timestamp': current_time,
                    'connection': {},
                    'block_name': 'registers',
                    'data': {}
                }
                if not self.client.is_open:
                    self.initialized = False

                # Try to re-initialize if connection lost
                if not self.initialized:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False
                    self.agent.start('init_generator')
                    self.agent.wait('init_generator')

                # Only get readings if connected
                if self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': True}})

                    regdata = self.read_cycle(self.client)

                    if regdata:
                        for reg in regdata:
                            data['data'][reg] = regdata[reg]["value"]
                            field_dict = {reg: regdata[reg]}
                            session.data['fields'].update(field_dict)
                    else:
                        self.log.info(f'Connection error or error in processing data.')
                        self.initialized = False
                        time.sleep(1)

                session.data.update({'timestamp': current_time})

                # Continue trying to connect
                if not self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': False}})
                    self.log.info('Trying to reconnect.')
                    time.sleep(1)
                    continue

                self.agent.publish_to_feed('generator', data)

                time.sleep(1)

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
    pgroup.add_argument('--read-config', type=str,
                        help="Path to config file.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Not used anymore, but we don't it to break the agent if these args are passed
    parser.add_argument('--fake-data', help=argparse.SUPPRESS)
    parser.add_argument('--num-channels', help=argparse.SUPPRESS)

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='GeneratorAgent',
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

    agent, runner = ocs_agent.init_site_agent(args)

    p = GeneratorAgent(agent,
                       host=args.host,
                       port=int(args.port),
                       read_config=args.read_config)

    agent.register_task('init_generator', p.init_generator,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
