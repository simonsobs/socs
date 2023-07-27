import argparse
import time
import os

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from pyModbusTCP.client import ModbusClient

def convert_RPM(val):
    return val/10.
def convert_pressure(val):
    return val/1000.

class VLT:
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

    def __init__(self, host, port, unit_id=1):
        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.client = ModbusClient(self.host, self.port, unit_id=self.unit_id, auto_open=True, auto_close=False)
        self.client.open()


    def read_cycle(self):
        print('in_read_cycle')
        try:
            this_cycle_data = {}
            speed, press_low, press_high = self.client.read_holding_registers(2911,3)
            press_high=convert_pressure(press_high)
            press_low=convert_pressure(press_low)
            speed = convert_RPM(speed)
            #this_cycle_data = {'fields': {'High_side_pressure': {'value':press_high, 'units': 'bar'}, 'Low_side_pressure': {'value':press_low, 'units':'bar'}, 'Pump_speed': {'value': speed, 'units':'RPM'}}}

            this_cycle_data = {'High_side_pressure': {'value':press_high, 'units': 'bar'}, 'Low_side_pressure': {'value':press_low, 'units':'bar'}, 'Pump_speed': {'value': speed, 'units':'RPM'}}
            print(this_cycle_data)
            return this_cycle_data
        except:
            pass

class VLTAgent:
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

    def __init__(self, agent, host='localhost', port=23, unit_id=1, sample_interval=5.):

        self.host = host
        self.port = port
        self.unit_id = unit_id
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()


        self.pacemaker_freq = 1. / sample_interval

        self.initialized = False
        self.take_data = False

        self.VLT = None

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('VLT',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def _connect(self):
        """connect()
        Instantiates Generator object and check if client is open
        """

        self.VLT = VLT(self.host, self.port, self.unit_id)
        if self.VLT.client.is_open:
            self.initialized = True
        else:
            self.initialized = False

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_VLT(self, session, params=None):
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
                return False, 'Could not connect to VLT'

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

            session.set_status('running')

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
                if not self.VLT.client.is_open:
                    self.initialized = False

                # Try to re-initialize if connection lost
                if not self.initialized:
                    self._connect()

                # Only get readings if connected
                if self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': True}})
                    session.data['address'] = self.host

                    regdata = self.VLT.read_cycle()
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
                    self.agent.publish_to_feed('VLT', _data)

            self.agent.feeds['VLT'].flush_buffer()

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
    pgroup.add_argument("--unit_id", default=5021,
                        help="Unit ID on serial bus.")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument("--sample-interval", type=float, default=10., help="Time between samples in seconds.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='VLTAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = VLTAgent(agent,
                       host=args.host,
                       port=int(args.port),
                       unit_id=int(args.unit_id),
                       sample_interval=args.sample_interval)

    agent.register_task('init_VLT', p.init_VLT,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
