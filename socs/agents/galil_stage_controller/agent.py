import argparse
import os
import time

import numpy as np
import txaio
import toml ## TODO: switch to .yaml??
import yaml

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from twisted.internet import reactor


from socs.agents.galil_stage_controller.drivers import GalilStage

class GalilStageControllerAgent:
    """ Agent to connect to galil linear stage motors for SAT coupling optics for passband measurements on-site.

    Args:
        ip (str): IP address for the Galil Stage Motor Controller
        config-file (str): .toml config file for initializing hardware axes
        port (int, optional): TCP port to connect, default is 23
    """

    def __init__(self, agent, ip, port=23):
        self.lock = TimeoutLock()
        self.agent = agent
        self.log = agent.log
        self.ip = ip
        self.port = port

        self.initialized = False
        self.take_data = False

        # Register data feeds
        agg_params = {
            'frame_length': 60,
        }

        self.agent.register_feed('stage_status',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)


    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params=None):
        """init(auto_acquire=False)

        **Task** - Initalizes connection to the galil stage controller

        Parameters:
            auto_acquire(bool): Automatically start acq process after initialization
                if True. Defaults to False.

        """
        if self.initialized:
            return True, "Already initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              "{self.lock.job} is already running")
                return False, "Could not acquire lock."
            
            # Establish connection to galil stage controller
            self.stage = GalilStage(self.ip, self.port)
            #print('self.ip is ', self.ip)
            #print('self.configfile is', self.configfile)

            # test connection and display identifying info
            try:
                self.stage.get_data()
            except ConnectionError:
                self.log.error("Could not establish connection to galil stage motor controller")
                return False, "Galil Stage Controller agent initialization failed"


        self.initialized = True

        # start data acquistion if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Galil Stage Controller agent initialized"

        
    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acquisition of data from the Galil Stage Controller.

        Parameters:
            test_mode (bool, optional): Run the process loop only once.
                This is menat only for testing. Default is False.

        """
        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} is already running")
                return False, "Could not acquire lock."

            last_release = time.time()

            self.take_data = True
                

            pm = Pacemaker(1)#, quantize=True)
            while self.take_data:
                pm.sleep()
                # Reliqinuish sampling lock occassionally
                if time.time() - last_release > 1:
                    last_release  = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                try:
                    data = self.stage.get_data()
                    self.log.debug("{data}", data=session.data)
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from galil stage controller. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue

                session.data = {"data": data,
                                "timestamp": time.time()}
                
                pub_data = {'timestamp': time.time(),
                            'block_name': 'stage_status',
                            'data': {}}
                
                pub_data['data'] = data
                
                self.agent.publish_to_feed('stage_status', pub_data)

                if params['test_mode']:
                    break
                
        self.agent.feeds['stage_status'].flush_buffer()

        return True, 'Acquisition exited cleanly.'


    def _stop_acq(self, session, params):
        """Stops acquisition of data from the galil stage controller"""
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


        
def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automaticall build documenation based on this function.

    
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip')
    pgroup.add_argument('--configfile')
    pgroup.add_argument('--port', default=23)
    pgroup.add_argument('--mode', choices=['init', 'acq'])


    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='GalilStageControllerAgent',
                                  parser=parser,
                                  args=args)

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
    stage = GalilStageControllerAgent(agent, args.ip, args.port)
    agent.register_task('init', stage.init, startup=init_params)
    agent.register_process('acq', stage.acq,  stage._stop_acq)

    runner.run(agent, auto_reconnect = True)



if __name__ == '__main__':
    main()
