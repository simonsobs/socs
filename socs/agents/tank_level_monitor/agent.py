import argparse
import os
import struct
import time

import serial
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock


class TankLevelMonitor:

    """Initialize serial communication with tank sensors & creates dicts to store data depending on tanks numbers."""

    def __init__(self):

        self.client = serial.Serial("/dev/ttyUSB1", 9600, timeout=0.5)

        self.tank_data = {}  # Define dictionary for Tank data, 7 fields
        self.tank1_data = {}
        self.tank2_data = {}
        self.tank1_data_fields = ['Tank1_vol', 'Net1_vol', 'emp1_vol', 'prod1_h', 'water1_h', 'avg1_temp', 'water1_vol']
        self.tank2_data_fields = ['Tank2_vol', 'Net2_vol', 'emp2_vol', 'prod2_h', 'water2_h', 'avg2_temp', 'water2_vol']

        self.tank_data_ok = False
        self.tank_length_to_read = 89
        self.verbose = True

        self.client.flushOutput()

    def tank_data_checker(self, tank_num):
        self.tank_data_ok = False

        if len(self.full_data) == 89:
            if self.full_data[18:19] != b'':
                if self.verbose:
                    print("IN DATA CHECKER 1: ", self.full_data[0:2])
                if self.full_data[0:2] == b'\x01i':
                    if self.verbose:
                        print("IN DATA CHECKER 2:", self.full_data[88:89])
                    if self.full_data[88:89] == b'\x03':
                        if self.verbose:
                            print("IN DATA CHECKER 3:", self.full_data[18:19])
                        if int(self.full_data[18:19]) == int(tank_num):
                            if self.verbose:
                                print("DATA IS OK")
                            self.tank_data_ok = True

    def tank_data_verbosity(self, tank_num, msg=""):

        if self.verbose:
            print("Tank Number: ", tank_num)
            print(msg, self.full_data)

    """Recieves tank number (default tank1) and returns non decoded data."""

    def tank_data_reader(self, tank_num=1):

        self.client.flushOutput()
        self.client.flushInput()

        self.client.write(b'01i201' + tank_num)  # Inquiry <SOH>i201TT = 01 i201tank_num
        self.full_data = {}
        self.full_data = self.client.read(self.tank_length_to_read)

        self.tank_data_checker(tank_num)

        while True:
            self.tank_data_verbosity(tank_num, "Entering while loop in tank_data_reader")
            self.tank_data_checker(tank_num)
            if self.tank_data_ok:
                break
            else:
                self.client.flushOutput()
                self.client.write(b'01i201' + tank_num)
                self.full_data = {}
                self.full_data = self.client.read(self.tank_length_to_read)
                self.tank_data_verbosity(tank_num, "After tank_data_ok got False, full data: ")
                self.client.flushOutput()
                self.client.flushInput()
                time.sleep(10)

        if self.verbose:
            print(tank_num, self.full_data)

    """Recieves undecoded hex data and returns a dictionary with decoded & corrected data."""

    def tank_decode_data(self, tank_num):

        multfactor = [3.785, 3.785, 3.785, 2.54 / 100, 2.54 / 100, 5 / 9, 3.785]  # correction factor
        addfactor = [0, 0, 0, 0, 0, -32, 0]

        data = {}
        data = self.full_data[26:26 + 8 * 7]

        for i in range(7):
            data_field = data[i * 8:(i + 1) * 8]  # moving through all data
            decoded_data = struct.unpack('!f', bytes.fromhex(data_field.decode('ascii')))[0]  # decode hex to ieee float

            if tank_num == b'01':
                self.tank1_data[self.tank1_data_fields[i]] = (decoded_data + addfactor[i]) * multfactor[i]
            elif tank_num == b'02':
                self.tank2_data[self.tank2_data_fields[i]] = (decoded_data + addfactor[i]) * multfactor[i]

    def read_cycle(self):

        self.tank_data_reader(b'01')
        self.tank_decode_data(b'01')

        self.tank_data_reader(b'02')
        self.tank_decode_data(b'02')

        self.tank_data = self.tank1_data
        self.tank_data.update(self.tank2_data)

        if self.verbose:
            print("READ CYCLE: ", self.tank_data)

        try:
            this_cycle_data = {}
            for key in self.tank_data:
                this_cycle_data[key] = {'value': self.tank_data[key]}
            if self.verbose:
                print(this_cycle_data)
            return this_cycle_data
        except BaseException:
            pass


class TankLevelMonitorAgent:
    """Monitor the External fuel Tank level  via Serial COM.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
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

    def __init__(self, agent, unit=1, sample_interval=15.):

        self.unit = unit
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.pacemaker_freq = 1. / sample_interval

        self.initialized = False
        self.take_data = False

        self.TankLevelMonitor = None

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('TankLevelMonitor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def _connect(self):
        """connect()
        Instantiates tank level monitor  object and mark it as initialized.
        """
        self.TankLevelMonitor = TankLevelMonitor()
        self.initialized = True

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_TankLevelMonitor(self, session, params=None):
        """init_generator(auto_acquire=False)

        **Task** - Perform first time setup of the VLT.

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
                return False, 'Could not connect to Tank Monitor'

        # Start data acquisition if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Tank Level Monitor initialized.'

    @ocs_agent.param('_')
    def acq(self, session, params=None):

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
                if not self.TankLevelMonitor.client.is_open:
                    self.initialized = False

                """Try to re-initialize if connection lost"""
                if not self.initialized:
                    self._connect()

                """ Only get readings if connected"""
                if self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': True}})

                    regdata = self.TankLevelMonitor.read_cycle()

                    if regdata:
                        for reg in regdata:
                            data['data'][reg] = regdata[reg]["value"]
                            field_dict = {reg: regdata[reg]['value']}
                            session.data['fields'].update(field_dict)
                        session.data.update({'timestamp': current_time})
                    else:
                        self.log.info('Connection error or error in processing data.')
                        self.initialized = False

                """ Continue trying to connect"""
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
                    self.agent.publish_to_feed('TankLevelMonitor', _data)

            self.agent.feeds['TankLevelMonitor'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.TankLevelMonitor.verbose:
            print("DEBUG: stops acq process:  ", self.take_data)
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument("--unit", default=1,
                        help="unit to listen to.")
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument("--sample-interval", type=float, default=15., help="Time between samples in seconds.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='TankLevelMonitorAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}
    # print('init_params', init_params)
    agent, runner = ocs_agent.init_site_agent(args)

    p = TankLevelMonitorAgent(agent,
                              unit=int(args.unit),
                              sample_interval=args.sample_interval)

    agent.register_task('init_TankLevelMonitor', p.init_TankLevelMonitor,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
