import argparse
import os
import socket
import time

import numpy
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock


class LDMonitor:
    """Receives and decodes data of the lightning detector via UDP

    Parameters
    ----------
    host : str
        Address of the computer reading the data.
    port : int
        Port of host where data will be received, default 1110.

    Attributes
    ----------
    port : int
        Port number in the local host to be bound to receive the data
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    sockopen : bool
        Indicates when the socket is open
    inittime : float
        Logs the time at which initialization was carried out
    data_dict : dictionary
        Dictionary data stored from the lightning detector
    newdata_dict : dictionary
        Dictionary where new data is received
    """

    def __init__(self, port=1110):
        self.port = port
        self.log = txaio.make_logger()

        # check if socket has been opened
        if hasattr(self, 'sockopen'):
            if self.sockopen:
                self.sock.close()
                self.log.info('Socket closed preemptively')

        # open and bing socket to receieve lightning detector data
        try:
            self.log.info('Opening socket')
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except BaseException:
            self.log.info('Failed to create socket')

        try:
            self.log.info('Binding socket')
            self.sock.bind(('', self.port))
            self.sockopen = True
            self.inittime = time.time()
        except BaseException:
            self.log.info('Failed to bind socket')

        # initialize variables to account for absence of previous data
        self.data_dict = {
            'd_type': numpy.nan,
            'field_value': numpy.nan,
            'rot_fault': 0,
            'time_last': -1.,
            'tsince_last': -1.,
            'dist': -1,
            'unit_d': 0,
            'high_field': -1,
            'hifield_value': -1000.,
            'alarm_r': 0,
            'alarm_o': 0,
            'alarm_y': 0,
            'delay_g': 1,
            'clear': 0,
            'r_timer': 0,
            'o_timer': 0,
            'y_timer': 0,
            'g_timer': 0,
            'allclear_timer': 0,
            'faultcode': 0
        }

        self.log.info('LDMonitor function initialized')

    def read_data(self):
        """
        Receives data from the lightning detector via UDP,
        and returns a dictionary containing formatted data
        """

        self.data, _ = self.sock.recvfrom(1024)
        self.data = self.data.decode('utf-8')

        # "e-field" sentence
        if self.data[0] == '$':
            data_split = self.data[1:].split(',')
            rot_fault = int(data_split[1].split('*')[0])
            self.newdata_dict = {
                'd_type': 0,
                'field_value': float(data_split[0]),
                'rot_fault': rot_fault
            }
            self.data_dict.update(self.newdata_dict)
            return self.data_dict

        elif self.data[0] == '@':
            param = self.data[1:3]

            # "lightning strike" sentence
            if param == 'LI':
                data_split = self.data.split(',')[1:]
                if data_split[1].split('*')[0] == 'Miles':
                    unit_d = 0
                elif data_split[1].split('*')[0] == 'Km':
                    unit_d = 1

                self.newdata_dict = {
                    'd_type': 1,
                    'time_last': time.time(),
                    'dist': int(data_split[0]),
                    'unit_d': unit_d
                }
                self.data_dict.update(self.newdata_dict)

                self.log.info('Lightning strike detected!')

                return self.data_dict

            # "high e-field" sentence, account for 2 types
            elif param == 'HF':
                data_split = self.data[1:].split(',')
                if len(data_split) == 1:
                    self.newdata_dict = {
                        'd_type': 2,
                        'high_field': 1,
                        'hifield_value': float(self.data_dict['field_value'])
                    }
                else:
                    self.newdata_dict = {
                        'd_type': 2,
                        'hifield_value': float(data_split[1])
                    }
                self.data_dict.update(self.newdata_dict)
                return self.data_dict

            # "status" sentence
            elif param == 'ST':
                faultcode = int(self.data.split(',')[-1].split('*')[0], 16)
                data_split = [int(i) for i in self.data.split(',')[1:-1]]

                self.newdata_dict = {
                    'd_type': 3,
                    'alarm_r': data_split[0],
                    'alarm_o': data_split[1],
                    'alarm_y': data_split[2],
                    'delay_g': data_split[3],
                    'clear': data_split[4],
                    'r_timer': data_split[5],
                    'o_timer': data_split[6],
                    'y_timer': data_split[7],
                    'g_timer': data_split[8],
                    'allclear_timer': data_split[9],
                    'faultcode': faultcode
                }

                self.data_dict.update(self.newdata_dict)
                return self.data_dict

            # disregard "alarm timers" sentence, but update sentence type
            elif param == 'WT':
                self.newdata_dict = {'d_type': 4}
                self.data_dict.update(self.newdata_dict)
                return self.data_dict

    def read_cycle(self):
        """
        In each cycle data is read and then parsed following
        the format required to publish data to the ocs feed
        """
        try:
            self.read_data()

            # updates time since last strike if strike data exists
            if self.data_dict['time_last'] == -1.:
                self.data_dict['tsince_last'] = -1.
            else:
                self.data_dict['tsince_last'] = (time.time()
                                                 - self.data_dict['time_last'])

            return self.data_dict

        except BaseException:
            pass
            self.log.info('LD data read error, passing to next data iteration')


class LDMonitorAgent:
    """Monitor the Lightning Detector data via UDP.

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

    def __init__(self, agent, sample_interval=15.):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.pacemaker_freq = 1. / sample_interval

        self.initialized = False
        self.take_data = False

        self.LDMonitor = None

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('ld_monitor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def _connect(self):
        """connect()
        Instantiates LD object and check if client is open
        """

        self.LDMonitor = LDMonitor()
        self.initialized = True

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_ld_monitor(self, session, params=None):
        """init_ld_monitor(auto_acquire=False)

        **Task** - Perform first time setup of the LD.

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
                return False, 'Could not connect to LD'

        # Start data acquisition if requested
        if params['auto_acquire']:
            self.agent.start('acq')
        return True, 'LD initialized.'

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()

        **Process** - Starts the data acquisition process

        Notes
        _____
        The most recent data collected is stored in session data in the
        structure::

            >>> response.session['data']
            {'fields':{
                'd_type': 3, 'field_value': 0.28, 'rot_fault': 0,
                'time_last': -1.0, 'tsince_last': -1.0, 'dist': -1, 'unit_d': 0,
                'high_field': -1, 'hifield_value': -1000.0, 'alarm_r': 0,
                'alarm_o': 0, 'alarm_y': 0, 'delay_g': 1, 'clear': 1, 'r_timer': 0,
                'o_timer': 0, 'y_timer': 0, 'g_timer': 0, 'allclear_timer': 0,
                'faultcode': 0
                },
                ...
                'connection': {
                    'conn_timestamp': 1711285858.1063662,
                    'connected': True}, 'data_timestamp': 1711285864.6254003
                    }
            }

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
                    'data': {}
                }
                if not self.LDMonitor.sockopen:
                    self.initialized = False

                # Try to re-initialize if connection lost
                if not self.initialized:
                    self._connect()

                # Only get readings if connected
                if self.initialized:
                    session.data.update({'connection': {'conn_timestamp': self.LDMonitor.inittime,
                                                        'connected': True}})

                    ld_data = self.LDMonitor.read_cycle()

                    if ld_data:
                        for key, value in ld_data.items():
                            data['data'][key] = value
                        session.data.update({'data_timestamp': current_time,
                                             'fields': ld_data})
                        self.log.debug(ld_data)
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
                    self.agent.publish_to_feed('ld_monitor', _data)

            self.agent.feeds['ld_monitor'].flush_buffer()

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
    pgroup.add_argument('--mode', type=str, choices=['idle', 'init', 'acq'],
                        help="Starting action for the agent.")
    pgroup.add_argument("--sample-interval", type=float, default=.2, help="Time between samples in seconds.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='LDMonitor',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested (default)
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}
    print('init_params', init_params)
    agent, runner = ocs_agent.init_site_agent(args)

    p = LDMonitorAgent(agent, sample_interval=args.sample_interval)
    agent.register_task('init_ld_monitor', p.init_ld_monitor,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
