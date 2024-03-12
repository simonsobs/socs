import socket
import numpy
import time
import os
import argparse
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker,TimeoutLock

verbosity=False

class ld_monitor:
    """Receives and decodes data of the lightning detector via UDP

    Parameters
    ----------
    host : str
        Address of the computer reading the data.
    port : int
        Port of host where data will be received, default 1110.
    verbose : boolean
        Defines verbosity of the function (debug purposes).

    Attributes
    ----------
    verbose : bool
        Defines verbosity for debugging purposes
    host : string
        Defines the host where data will be received (where the agent is to be ran)
    port : int
        Port number in the local host to be bound to receive the data
    sockopen : bool
        Indicates when the socket is open
    inittime : float
        Logs the time at which initialization was carried out
    data_dict : dictionary
        Raw data received from the lightning detector
    newdata_dict : dictioanry
        The dictionary where new data is received
    """

    def __init__(self,port=1110,verbose=verbosity):        
        self.verbose=verbose
        self.port=port

        # get localhost ip
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            self.host=s.getsockname()[0]
        
        if hasattr(self,'sockopen'):
            self.sock.close()

        # open and bind socket to receive lightning detector data
        try:
            self.sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        except:
            print('Failed to create socket')
                
        try:
            self.sock.bind((self.host,self.port))
            self.sockopen=True
            self.inittime=time.time()
        except:
            print('Failed to bind socket')
   
        # initialize variables to account for absence of previous data
        self.data_dict={
            'd_type':numpy.nan,
            'field_value':numpy.nan,
            'rot_fault':0,
            'time_last':-1.,
            'tsince_last':-1.,
            'dist':-1,
            'unit_d':0,
            'high_field':-1,
            'hifield_value':-1000.,
            'alarm_r':0,
            'alarm_o':0,
            'alarm_y':0,
            'delay_g':1,
            'clear':0,
            'r_timer':0,
            'o_timer':0,
            'y_timer':0,
            'g_timer':0,
            'allclear_timer':0,
            'faultcode':0
            }
        
        if self.verbose:
            print('ld_monitor function monitor initialized')

    def read_data(self):
        """
        Receives data from the lightning detector via UDP,
        and returns a dictionary containing formatted data
        """

        self.data, _ = self.sock.recvfrom(1024)
        self.data=self.data.decode('utf-8')
        
        # receiving an "e-fiel" sentence
        if self.data[0]=='$':
            data_split=self.data[1:].split(',')
            rot_fault=int(data_split[1].split('*')[0])
            self.newdata_dict={
                'd_type':0,
                'field_value':float(data_split[0]),
                'rot_fault':rot_fault
                }
            self.data_dict.update(self.newdata_dict)
            return self.data_dict
        
        elif self.data[0]=='@':
            param=self.data[1:3]
  
            match param:
                # receiving a "lightning strike" sentence
                case 'LI':
                    data_split=self.data.split(',')[1:]
                    if data_split[2].split('*')[0]=='Miles':
                        unit_d=0
                    elif data_split[2].split('*')[0]=='Km':
                        unit_d=1

                    self.newdata_dict={
                        'd_type':1,
                        'time_last':time.time(),
                        'dist':int(data_split[1]),
                        'unit_d':unit_d
                        }
                    self.data_dict.update(self.newdata_dict)

                    return self.data_dict
                
                # receiving a "high e-field" sentence, account for 2 types
                case 'HF':
                    data_split=self.data[1:].split(',')
                    if len(data_split)==1:
                        self.newdata_dict={
                            'd_type':2,
                            'high_field':1,
                            'hifield_value':float(self.data_dict['field_value'])
                            }
                    else:
                        self.newdata_dict={
                            'd_type':2,
                            'hifield_value':float(data_split[1])
                            }
                    self.data_dict.update(self.newdata_dict)
                    return self.data_dict
                
                # status sentence
                case 'ST':
                    faultcode=int(self.data.split(',')[-1].split('*')[0],16)
                    data_split=[int(i) for i in self.data.split(',')[1:-1]]
                    
                    self.newdata_dict={
                        'd_type':3,
                        'alarm_r':data_split[0],
                        'alarm_o':data_split[1],
                        'alarm_y':data_split[2],
                        'delay_g':data_split[3],
                        'clear':data_split[4],
                        'r_timer':data_split[5],
                        'o_timer':data_split[6],
                        'y_timer':data_split[7],
                        'g_timer':data_split[8],
                        'allclear_timer':data_split[9],
                        'faultcode':faultcode
                        }
                    
                    self.data_dict.update(self.newdata_dict)
                    return self.data_dict

                # disregard "alarm timers" sentence but update sentence type
                case 'WT':
                    self.newdata_dict={'d_type':4}
                    self.data_dict.update(self.newdata_dict)
                    return self.data_dict

    def read_cycle(self):
        """
        In each cycle data is read and then parsed following
        the format required to publish data to the ocs feed
        """
        try:
            cycle_data={}
            self.read_data()
            
            # updates time since last strike if previous strike data exists
            if self.data_dict['time_last']==-1.:
                self.data_dict['tsince_last']=-1.
            else:
                self.data_dict['tsince_last']=(time.time()
                                              -self.data_dict['time_last'])
            
            # parse data to ocs agent feed format
            for key in self.data_dict:
                cycle_data[key]={'value':self.data_dict[key]}
            
            if self.verbose==True:
                print(cycle_data)
            return cycle_data

        except:
            pass
            if self.verbose:
                print('Passing to next data iteration')
        
class ld_monitorAgent:
    """Monitor the Lightning Detector data via UDP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    unit : int
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

        self.ld_monitor= None

        agg_params = {
            'frame_length':10*60 # [sec]
        }
        self.agent.register_feed('ld_monitor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def _connect(self):
        """connect()
        Instantiates LD object and check if client is open
        """
        self.ld_monitor= ld_monitor(verbose=verbosity)
        self.initialized = True

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_ld_monitor(self, session, params=None):
        """
        Perform first time setup of the LD.

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
                return False, 'Could not connect to LD'

        # Start data acquisition if requested
        if params['auto_acquire']:
            self.agent.start('acq')
        return True, 'LD initialized.'

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()
        
        Starts the data acquisition process
        
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
                if self.ld_monitor.sockopen==False:
                    self.initialized = False

                #Try to re-initialize if connection lost
                if not self.initialized:
                    self._connect()

                # Only get readings if connected
                if self.initialized:
                    session.data.update({'connection': {'last_attempt': time.time(),
                                                        'connected': True}})

                    regdata = self.ld_monitor.read_cycle()
                    
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
    args = site_config.parse_args(agent_class='ld_monitor',
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
    
    p = ld_monitorAgent(agent,
                       unit=int(args.unit),
                       sample_interval=args.sample_interval)
    agent.register_task('init_ld_monitor', p.init_ld_monitor,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
