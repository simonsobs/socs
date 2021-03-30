import os
import argparse
import time
import txaio

## yes I shouldn't have named that module agent
from xy_agent.xy_connect import XY_Stage

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class XY_Agent:
    """
    Agent for connecting to the LATRt XY Stages
    Args: name
          ip_addr -- IP address where RPi server is running
          port    -- Port the RPi Server is listening on
    """

    def __init__(self, agent, ip_addr, port):
        
        self.ip_addr = ip_addr
        self.port = port
        
        self.xy_stage = None
        self.initialized = False
        self.take_data = False
        self.is_moving = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        ### register the position feeds
        agg_params = {
            'frame_length' : 10*60, #[sec] 
        }

        self.agent.register_feed('positions',
                                 record = True,
                                 agg_params = agg_params,
                                 buffer_time = 1)
    
    def init_xy_stage_task(self, session, params=None):
        """init_xy_stage_task(params=None)
        Perform first time setup for communivation with XY stages.
        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.
        Parameters:
        """

        if params is None:
            params = {}

        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")
            try:
                self.xy_stage = XY_Stage(self.ip_addr, self.port)
                self.xy_stage.init_stages()
        
                print("XY Stages Initialized")
            except ValueError:
                    pass
        # This part is for the record and to allow future calls to proceed, so does not require the lock
        self.initialized = True
        return True, 'XY Stages Initialized.'

    def move_x_cm(self, session, params):
        """
        params: dict: { 'distance': float, 'velocity':float < 1.2}
        """

        with self.lock.acquire_timeout(timeout=3, job='move_x_cm') as acquired:
            if not acquired:
                self.log.warn(f"Could not start x move because lock held by {self.lock.job}")
                return False
            self.xy_stage.move_x_cm( params['distance'], params['velocity'])
        
        self.lock.release()
        time.sleep(1)
        while True:
            ## data acquisition updates the moving field if it is running
            if not self.take_data:
                with self.lock.acquire_timeout(timeout=3, job='move_x_cm') as acquired:
                    if not acquired:
                        self.log.warn(f"Could not check because lock held by {self.lock.job}")
                        return False
                    self.is_moving = self.xy_stage.moving
                self.lock.release()
            if not self.is_moving:
                break
        return True

    def move_y_cm(self, session, params):
        """
        params: dict: { 'distance': float, 'velocity':float < 1.2}
        """

        with self.lock.acquire_timeout(timeout=3, job='move_y_cm') as acquired:
            if not acquired:
                self.log.warn(f"Could not start y move because lock held by {self.lock.job}")
                return False
            self.xy_stage.move_y_cm( params['distance'], params['velocity'])
        
        self.lock.release()
        time.sleep(1)
        while True:
            ## data acquisition updates the moving field if it is running
            if not self.take_data:
                with self.lock.acquire_timeout(timeout=3, job='move_y_cm') as acquired:
                    if not acquired:
                        self.log.warn(f"Could not check for move because lock held by {self.lock.job}")
                        return False
                    self.is_moving = self.xy_stage.moving
                self.lock.release()
            if not self.is_moving:
                break
        return True

 
    def set_position(self, session, params):
        """
        params: dict: {'position': (float, float)}
        """
        with self.lock.acquire_timeout(timeout=3, job='set_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not set position because lock held by {self.lock.job}")
                return False
                        
            self.xy_stage.position = params['position']

    def start_acq(self, session, params):
        """
        params: dict: {`sample_rate': float, sampling rate in Hz}
        """
        pass    
        f_sample = params.get('sampling_rate', 2)
        sleep_time = 1/f_sample - 0.1
        if not self.initialized:
            self.init_xy_stage_task(session)
        
        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.log.info("Starting Data Acquisition for XY Stages")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

            while self.take_data:
                if time.time()-last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False
                
                data = {'timestamp':time.time(), 'block_name':'positions','data':{}}
                pos = self.xy_stage.position
                self.is_moving = self.xy_stage.moving

                data['data']['x'] = pos[0]
                data['data']['y'] = pos[1] 
                self.agent.publish_to_feed('positions',data)
                self.agent.feeds['positions'].flush_buffer()
                time.sleep(sleep_time)

        return True, 'Acquisition exited cleanly.'
    
    def stop_acq(self, session, params=None):
        """
        params: dict: {}
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'
    
def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--port')

    return parser


if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    # Get the default ocs argument parser.
    site_parser = site_config.add_arguments()

    parser = make_parser(site_parser)

    # Parse comand line.
    args = parser.parse_args()
    
    # Interpret options in the context of site_config.
    ## I don't really know if I need this
    site_config.reparse_args(args, 'XY_StageAgent')
    agent, runner = ocs_agent.init_site_agent(args)

    xy_agent = XY_Agent(agent, args.ip_address, args.port)

    agent.register_task('init_xy_stage', xy_agent.init_xy_stage_task)
    agent.register_task('move_x_cm', xy_agent.move_x_cm)
    agent.register_task('move_y_cm', xy_agent.move_y_cm)
    agent.register_task('set_position', xy_agent.set_position)
    
    agent.register_process('acq', xy_agent.start_acq, xy_agent.stop_acq)

    runner.run(agent, auto_reconnect=True)
