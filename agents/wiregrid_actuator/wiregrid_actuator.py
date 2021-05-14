import sys, os, argparse, time

'''
this_dir = os.path.dirname(__file__)
sys.path.append(
        os.path.join(this_dir, 'src'))

import pmx as pm
import command as cm
'''

from ocs import ocs_agent, site_config, client_t
from ocs.ocs_twisted import TimeoutLock

# Limit Switch / Stopper class
from src.LimitSwitch import LimitSwitch
from src.Stopper     import Stopper
import limitswitch_config
import stopper_config

class WiregridActuatorAgent:
    def __init__(self, agent, interval_time=1):
        self.agent = agent
        self.log   = agent.log
        self.lock    = TimeoutLock()
        self.run_acq = False
        self.controlling = False
        self.interval_time = interval_time

        agg_params = {'frame_length': 60}
        self.agent.register_feed('WGActuator', record = True, agg_params = agg_params)
        
        self.limitswitch = LimitSwitch(limitswitch_config.GPIOpinInfo)
        self.stopper     = Stopper    (stopper_config    .GPIOpinInfo) 
        pass

    def move(self, session, params=None):
        with self.acquire_timeout(timeout=3, job='move') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in move().'

            # Running
            self.controlling = True
            #moving commands
            self.controlling = False
            pass
        return True, 'Finish move()'


    def get_onoff_limitswitch(self):
        onoffs = self.limitswitch.get_onoff()
        return onoffs;
    def get_onoff_stopper(self):
        onoffs = self.stopper.get_onoff()
        return onoffs;

    def start_acq(self, session, params=None):
        if params is None:
            params = {}

        # Define data taking interval_time 
        interval_time = params.get('interval_time')
        # If interval_time is None, use value passed to Agent init
        if interval_time is None:
            interval_time = self.interval_time
            pass

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in start_acq().'

        session.set_status('running')

        self.run_acq = True
        session.data = {'fields':{}}
        while self.run_acq:
            current_time = time.time()
            data = {'timestamp': current_time, 'block_name': 'actuator_onoff', 'data': {}}

            # Take data
            onoff_dict_ls = {}
            onoff_dict_st = {}
            if not self.controlling:
                # Get onoff
                onoff_ls = self.get_onoff_limitswitch()
                onoff_st = self.get_onoff_stopper()
                # Data for limitswitch
                for onoff, name in zip(onoff_ls, self.limitswitch.pinnames) : 
                    data['data']['limitswitch_{}'.format(name)] = onoff
                    onoff_dict_ls[name] = onoff
                    pass
                # Data for stopper
                for onoff, name in zip(onoff_st, self.stopper.pinnames) : 
                    data['data']['stopper_{}'.format(name)] = onoff
                    onoff_dict_st[name] = onoff
                    pass
            else :
                continue
                pass
            # publish data
            self.agent.publish_to_feed('WGActuator', data)
            # store session.data
            field_dict = {'limitswitch': onoff_dict_ls, 'stopper': onoff_dict_st}
            session.data['timestamp']=current_time
            session.data['fields']=field_dict
            print('data = {}'.format(field_dict));

            # wait an interval
            time.sleep(interval_time)
            pass

        self.agent.feeds['WGActuator'].flush_buffer()
        return True, 'Acquisition exited cleanly'

    def stop_acq(self, session, params=None):
        if self.run_acq : 
            self.run_acq = False
            session.set_status('stopping')
            return True, 'Stop data acquisition'
        session.set_status('??????')
        return False, 'acq is not currently running'


def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--interval-time', dest='interval_time', type=float, default=1,
                        help='')
    pgroup.add_argument('--actuator-dev', dest='actuator_dev', type=str, default='/dev/ttyUSB0',
                        help='')
    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()
    interval_time = args.interval_time
    actuator_dev  = args.actuator_dev

    site_config.reparse_args(args, 'WiregridActuatorAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    actuator_agent = WiregridActuatorAgent(agent, interval_time)
    agent.register_task('move', actuator_agent.move)
    agent.register_process('acq', actuator_agent.start_acq, actuator_agent.stop_acq,startup=True)

    runner.run(agent, auto_reconnect=True)

