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

# import classes / configs
from src.Actuator    import Actuator
from src.LimitSwitch import LimitSwitch
from src.Stopper     import Stopper
import limitswitch_config
import stopper_config

class WiregridActuatorAgent:
    def __init__(self, agent, actuator_dev='/dev/ttyUSB0', interval_time=1, sleep=0.10, verbose=0):
        self.agent = agent
        self.log   = agent.log
        self.lock    = TimeoutLock()
        self.run_acq = False
        self.controlling = False
        self.actuator_dev  = actuator_dev
        self.interval_time = float(interval_time)
        self.sleep  = sleep
        self.verbose       = verbose

        agg_params = {'frame_length': 60}
        self.agent.register_feed('WGActuator', record = True, agg_params = agg_params)
        
        try:
            self.actuator    = Actuator(self.actuator_dev, sleep=self.sleep, verbose=self.verbose)
        except Exception as e:
            msg = 'Failed to initialize Actuator instance! | Error = "actuator is None"'
            self.log.warn(msg)
            self.actuator = None
            pass
        self.limitswitch = LimitSwitch(limitswitch_config.GPIOpinInfo)
        self.stopper     = Stopper    (stopper_config    .GPIOpinInfo) 
        pass

    ######################
    # Internal functions #
    ######################

    def __check_connect(self):
        if self.actuator is None :
            msg = 'No connection to the actuator. | Error = "actuator is None"'
            self.log.warn(msg)
            return False, msg
        else :
            ret, msg = self.actuator.check_connect()
            if not ret :
                msg = 'No connection to the actuator. | Error = "%s"' %  msg
                self.log.warn(msg)
                return False, msg
            pass
        return True, 'Connection is OK.'

    def __reconnect(self):
        self.log.warn('*** Trying to reconnect... ***')
        # reconnect
        try :
            if self.actuator : del self.actuator
            self.actuator    = Actuator(self.actuator_dev, sleep=self.sleep, verbose=self.verbose)
        except Exception as e:
            msg = 'Failed to initialize Actuator! | Error: %s' % e
            self.log.warn(msg)
            self.actuator = None
            return False, msg
        # reinitialize cmd
        ret, msg = self.__check_connect()
        if ret :
            msg = 'Successfully reconnected to the actuator!'
            self.log.info(msg)
            return True, msg
        else :
            msg = 'Failed to reconnect to the actuator!'
            self.log.warn(msg)
            if self.actuator : del self.actuator
            self.actuator = None
            return False, msg


    def __forward(self, distance, speedrate=0.1):
        distance = abs(distance)
        LSL2 = 0 # left  actuator opposite limitswitch
        LSR2 = 0 # right actuator opposite limitswitch
        LSL2,LSR2 = self.limitswitch.get_onoff(pinname=['LSL2','LSR2'])
        if LSL2==0 and LSR2==0 : 
            status, msg = self.actuator.move(distance, speedrate)
            if status<0 : return False, msg
            pass
        isrun = True
        while LSL2==0 and LSR2==0 and isrun :
            LSL2,LSR2 = self.limitswitch.get_onoff(pinname=['LSL2','LSR2'])
            isrun = self.actuator.isRun()
            if self.verbose>0 : self.log.info('LSL2={}, LSR2={}, run={}'.format(LSL2,LSR2,isrun))
            pass
        self.actuator.hold()
        self.actuator.release()
        return True, 'Finish forward(distance={}, speedrate={})'.format(distance, speedrate)

    def __backward(self, distance, speedrate=0.1):
        distance = abs(distance)
        LSL1 = 0 # left  actuator limitswitch @ motor (outside)
        LSR1 = 0 # right actuator limitswitch @ motor (outside)
        LSL1,LSR1 = self.limitswitch.get_onoff(pinname=['LSL1','LSR1'])
        if LSL1==0 and LSR1==0 : 
            status, msg = self.actuator.move(-1*distance, speedrate)
            if status<0 : return False, msg
            pass
        isrun = True
        while LSL1==0 and LSR1==0 and isrun :
            LSL1, LSR1 = self.limitswitch.get_onoff(pinname=['LSL1','LSR1'])
            isrun = self.actuator.isRun()
            if self.verbose>0 : self.log.info('LSL1={}, LSR1={}, run={}'.format(LSL1,LSR1,isrun))
            pass
        self.actuator.hold()
        self.actuator.release()
        return True, 'Finish backward(distance={}, speedrate={})'.format(distance, speedrate)


    def  __insert(self, main_distance=850, main_speedrate=1.0):
            # check motor limitswitch
            LSL1,LSR1 = self.limitswitch.get_onoff(pinname=['LSL1','LSR1'])
            if LSL1==0 and LSR1==0 :
                self.log.warn('WARNING!: The limitswitch on motor side is NOT ON before inserting.')
                if main_speedrate>0.1 :  
                    self.log.warn('WARNING!: --> Change speedrate: {} --> 0.1'.format(main_speedrate))
                    main_speedrate = 0.1
                    pass
            else :
                self.log.info('The limitswitch on motor side is ON before inserting.')
                self.log.info('--> Checking connection to the actuator')
                # check connection
                ret, msg = self.__check_connect()
                self.log.info(msg)
                # reconnect
                if not ret :
                    self.log.warn('Trying to reconnect to the actuator...')
                    ret2, msg2 = self.__reconnect()
                    self.log.warn(msg2)
                    if not ret2 :
                        msg = 'Could not connect to the actuator even after reconnection!'
                        self.log.warn(msg)
                        self.log.warn('--> Stop inserting [__insert()] !')
                        return False
                        pass
                    pass
                pass

            # release stopper
            if self.stopper.set_allon() < 0 : 
                self.log.error('ERROR!: Stopper set_allon() --> STOP')
                return False
            if self.stopper.set_allon() < 0 : 
                self.log.error('ERROR!: Stopper set_allon() --> STOP')
                return False
            # forward a bit
            status, msg  = self.__forward(10, speedrate=0.1)
            if not status : 
                self.log.error('ERROR!:(in first forwarding) {}'.format(msg))
                return False
            # check limitswitch
            LSL1,LSR1 = self.limitswitch.get_onoff(pinname=['LSL1','LSR1'])
            print('LSL1,LSR1',LSL1,LSR1);
            if LSL1==1 or LSR1==1 :
                self.log.error('ERROR!: The limitswitch on motor side is NOT OFF after moving forward without stopper.')
                self.log.error('ERROR!: --> STOP')
                return False
            # power off stopper
            if self.stopper.set_alloff() < 0 : 
                self.log.error('ERROR!: Stopper set_alloff() --> STOP')
                return  False
            # main forward
            status, msg = self.__forward(main_distance, speedrate=main_speedrate)
            if not status : 
                self.log.error('ERROR!:(in main forwarding) {}'.format(msg))
                return False
            # last forward
            status, msg = self.__forward(200, speedrate=0.1)
            if not status : 
                self.log.error('ERROR!:(in last forwarding) {}'.format(msg))
                return False
            # check limitswitch
            LSL2,LSR2 = self.limitswitch.get_onoff(pinname=['LSL2','LSR2'])
            if LSL2==0 and LSR2==0 :
                self.log.error('ERROR!: The limitswitch on opposite side is NOT ON after forwardEdge. --> STOP')
                return False
            return True


    def __eject(self, main_distance=850, main_speedrate=1.0) :
            # check motor limitswitch
            LSL2,LSR2 = self.limitswitch.get_onoff(pinname=['LSL2','LSR2'])
            if LSL2==0 and LSR2==0 :
                self.log.warn('WARNING!: The limitswitch on opposite side (inside) is NOT ON before ejecting.')
                if main_speedrate>0.1 :  
                    self.log.warn('WARNING!: --> Change speedrate: {} --> 0.1'.format(main_speedrate))
                    main_speedrate = 0.1
                    pass
                pass


            # release stopper
            if self.stopper.set_allon() < 0 : 
                self.log.error('ERROR!: Stopper set_allon() --> STOP')
                return False
            if self.stopper.set_allon() < 0 : 
                self.log.error('ERROR!: Stopper set_allon() --> STOP')
                return False
            # backward a bit
            status, msg = self.__backward(10, speedrate=0.1)
            if not status : 
                self.log.error('ERROR!:(in first backwarding) {}'.format(msg))
                return False
            # check limitswitch
            LSL2,LSR2 = self.limitswitch.get_onoff(pinname=['LSL2','LSR2'])
            if LSL2==1 or LSR2==1 :
                self.log.error('ERROR!: The limitswitch on opposite side (inside) is NOT OFF after moving backward. --> STOP')
                return False
            # main backward
            status, msg = self.__backward(main_distance, speedrate=main_speedrate)
            if not status : 
                self.log.error('ERROR!:(in main backwarding) {}'.format(msg))
                return False
            # last backward
            status, msg = self.__backward(200, speedrate=0.1)
            if not status : 
                self.log.error('ERROR!:(in last backwarding) {}'.format(msg))
                return False
            # check limitswitch
            LSL1,LSR1 = self.limitswitch.get_onoff(pinname=['LSL1','LSR1'])
            if LSL1==0 and LSR1==0 :
                self.log.error('ERROR!: The limitswitch on motor side (outside) is NOT ON after backward. --> STOP')
                return False
            # power off stopper
            self.log.warn('WARNING!: Stopper set_alloff() --> STOP')
            if self.stopper.set_alloff() < 0 : 
                self.log.error('ERROR!: Stopper set_alloff() --> STOP')
                return  False
            return True


    ##################
    # Main functions #
    ##################

    def check_limitswitch(self, session, params=None):
        if params is None:
            params = {}
            pass
        pinname = params.get('pinname')
        onoffs = []
        msg = ''
        with self.lock.acquire_timeout(timeout=3, job='check_limitswitch') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in check_limitswitch().'
            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
            self.controlling = True
            onoffs    = self.limitswitch.get_onoff(pinname)
            self.controlling = False
            pinnames  = self.limitswitch.get_pinname(pinname)
            pinlabels = self.limitswitch.get_label(pinname)
            for i, pinname in enumerate(pinnames) :
                pinlabel = pinlabels[i]
                msg += '{:10s} ({:20s}) : {}\n'.format(pinname, pinlabel, 'ON' if onoffs[i] else 'OFF')
                pass
            pass
        self.log.info(msg)
        return onoffs, msg

    def check_stopper(self, session, params=None):
        if params is None:
            params = {}
            pass
        pinname = params.get('pinname')
        onoffs = []
        msg = ''
        with self.lock.acquire_timeout(timeout=3, job='check_stopper') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in check_stopper().'
            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
            self.controlling = True
            onoffs   = self.stopper.get_onoff(pinname)
            self.controlling = False
            pinnames = self.stopper.get_pinname(pinname)
            pinlabels= self.stopper.get_label(pinname)
            for i, pinname in enumerate(pinnames) :
                pinlabel = pinlabels[i]
                msg += '{:10s} ({:20s}) : {}\n'.format(pinname, pinlabel, 'ON' if onoffs[i] else 'OFF')
                pass
            pass
        self.log.info(msg)
        return onoffs, msg

    def insert(self, session, params=None):
        with self.lock.acquire_timeout(timeout=3, job='insert') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in insert().'

            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
         
            # Running
            self.controlling = True
            time.sleep(1)
         
            # Moving commands
            ret = self.__insert(850, 1.0)
            if not ret :
                self.log.error('Failed to insert!')
                return False, 'Failed insert() in __insert(850,1.0)'
         
            # Finishing
            self.controlling = False
            pass

        return True, 'Finish insert()'


    def eject(self, session, params=None):
        with self.lock.acquire_timeout(timeout=3, job='eject') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in eject().'

            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
         
            # Running
            self.controlling = True
            time.sleep(1)
         
            # Moving commands
            ret = self.__eject(850, 1.0)
            if not ret :
                self.log.error('Failed to insert!')
                return False, 'Failed eject() in __eject(850,1.0)'
         
            # Finishing
            self.controlling = False
            pass

        return True, 'Finish eject()'


    def insert_homing(self, session, params=None):
        with self.lock.acquire_timeout(timeout=3, job='insert_homing') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in insert_homing().'

            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
         
            # Running
            self.controlling = True
            time.sleep(1)
         
            # Moving commands
            ret = self.__insert(1000, 0.1)
            if not ret :
                self.log.error('Failed to insert_homing!')
                return False, 'Failed insert_homing() in __insert(1000,0.1)'
         
            # Finishing
            self.controlling = False
            pass

        return True, 'Finish insert_homing()'


    def eject_homing(self, session, params=None):
        with self.lock.acquire_timeout(timeout=3, job='eject_homing') as acquired:
            if not acquired:
                self.log.warn('Lock could not be acquired because it is held by {}.'.format(self.lock.job))
                return False, 'Could not acquire lock in eject_homing().'

            if self.controlling :
                self.log.warn('Actuator is controlled by another function.')
                return False, 'Actuator control is held by another function.'
         
            # Running
            self.controlling = True
            time.sleep(1)
         
            # Moving commands
            ret = self.__eject(1000, 0.1)
            if not ret :
                self.log.error('Failed to eject_homing!')
                return False, 'Failed eject_homing() in __eject(1000,0.1)'
         
            # Finishing
            self.controlling = False
            pass

        return True, 'Finish eject_homing()'


    def stop(self, session, params=None):
        self.log.warn('Try to stop and hold the actuator.')
        if self.controlling :
            self.log.warn('Actuator is controlled by another function.')
            pass
        
        self.controlling = True
        # This will disable move() command in Actuator class until release() is called.
        self.actuator.STOP = True 
        # Hold the actuator
        ret = self.actuator.hold()
        self.controlling = False

        return True, 'Finish stop()'


    def release(self, session, params=None):
        self.log.warn('Try to release the actuator.')
        if self.controlling :
            self.log.warn('Actuator is controlled by another function.')
            pass
        
        self.controlling = True
        # This will enable move() command in Actuator class.
        self.actuator.STOP = False
        # Relase the actuator
        ret = self.actuator.release()
        self.controlling = False

        return True, 'Finish release()'


    def reconnect(self, session, params=None):
        self.log.warn('reconnect() will power off the actuator for a short time.')
        self.log.warn('Usually, please don\'t use this task.')
        if self.controlling :
            self.log.warn('Actuator is controlled by another function.')
            pass
        # check connection
        ret, msg = self.__check_connect()
        self.log.warn(msg)
        # reconnect
        if ret :
            msg = 'Did not tried to reconnect the actuator.'
            self.log.warn(msg)
            return ret, msg
        else :
            self.controlling = True
            self.log.warn('Trying to reconnect to the actuator...')
            ret2, msg2 = self.actuator.__reconnect()
            self.controlling = False
            return ret2, msg2


    def start_acq(self, session, params=None):
        if params is None:
            params = {}
            pass

        # Define data taking interval_time 
        interval_time = params.get('interval-time')
        # If interval-time is None, use value passed to Agent init
        if interval_time is None :
            self.log.info('Not set by parameter of "interval-time" for start_acq()')
            interval_time = self.interval_time
        else :
            try:
                interval_time = float(interval_time)
            except ValueError as error:
                self.log.warn('Parameter of "interval-time" is incorrect : {}'.format(error))
                interval_time = self.interval_time
                pass
        self.log.info('interval time for acquisition of limitswitch&stopper = {} sec'.format(interval_time))

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
                onoff_ls = self.limitswitch.get_onoff()
                onoff_st = self.stopper.get_onoff()
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
            #print('data = {}'.format(field_dict))

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


    # End of class WiregridActuatorAgent


def make_parser(parser = None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--interval-time', dest='interval_time', type=float, default=1,
                        help='')
    pgroup.add_argument('--actuator-dev', dest='actuator_dev', type=str, default='/dev/ttyUSB0',
                        help='')
    pgroup.add_argument('--sleep', dest='sleep', type=float, default=0.10,
                        help='sleep time for every actuator command')
    pgroup.add_argument('--verbose', dest='verbose', type=int, default=0,
                        help='')
    return parser

if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'WiregridActuatorAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    interval_time = args.interval_time
    actuator_dev  = args.actuator_dev
    sleep         = args.sleep
    #print('interval_time = {} (type={})'.format(interval_time, type(interval_time)))
    #print('actuator_dev  = {} (type={})'.format(actuator_dev , type(actuator_dev)))
    actuator_agent = WiregridActuatorAgent(agent, actuator_dev, interval_time, sleep=sleep, verbose=args.verbose)
    agent.register_task('check_limitswitch', actuator_agent.check_limitswitch)
    agent.register_task('check_stopper', actuator_agent.check_stopper)
    agent.register_task('insert', actuator_agent.insert)
    agent.register_task('eject', actuator_agent.eject)
    agent.register_task('insert_homing', actuator_agent.insert_homing)
    agent.register_task('eject_homing', actuator_agent.eject_homing)
    agent.register_task('stop', actuator_agent.stop)
    agent.register_task('release', actuator_agent.release)
    agent.register_task('reconnect', actuator_agent.reconnect)
    agent.register_process('acq', actuator_agent.start_acq, actuator_agent.stop_acq,startup=True)

    runner.run(agent, auto_reconnect=True)

