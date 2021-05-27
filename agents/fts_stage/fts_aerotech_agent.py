import socket
import os
import time
import txaio
import argparse
from twisted.internet import reactor

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock, Pacemaker

class FTSAerotechStage:
    """
    Class for connecting to the FTS mirror controller

    Args:
        ip_address: IP address where controller is running
        port: Port the controller is listening on
        timeout: communication timeout
        speed: speed in mm/s, defaults to 25 mm/s if None
    """
    TRANSLATE = 1, 74.87
    LIMS = (-74.8,74.8)
    SPEED = 25 #mm/s
    INFLATION = 1.10
    SETTLE_T = 0.2
    MIN_WAIT = 0.1

    def __init__(self, ip_address, port, timeout=10, speed=None):
        self.ip_address = ip_address
        self.port = int(port)

        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)

        self.send('ENABLE X\n') #Send enable command
        data = self.comm.recv(1024) #Collect and print response
 
        if data == b'%\n':
            self.initialized = True
        else:
            self.initialized = False
        
        self.pos = None
        if speed is not None:
            self.SPEED = speed
        self.speed_code = 'F%i' % self.SPEED
        
 
    def send(self, msg):
        self.comm.sendall( bytes(msg, 'utf-8'))
    
    def read(self):
        # Controller blocks reply until motion is complete; so if
        # you're putting a timeout in here make sure it's smart/long
        # enough.
        return self.comm.recv(1024)
    
    def home(self):
        self.send('HOME X\n')
        time.sleep(0.1)
        ## block until homing is complete
        return self.read()
    
    def get_position(self):
        self.send('CMDPOS X\n')
        time.sleep(0.1)
        out = self.read()
        try:
            M, B = self.TRANSLATE
            self.pos = (float(out[1:])-B)/M
            return True, self.pos
        except:
            return False, None

    def move_to(self, position):
        lims = self.LIMS
        if position < lims[0] or position > lims[1]:
            return False, 'Move out of bounds!'
        M, B = self.TRANSLATE
        stage_pos = position*M + B
        cmd = ('MOVEABS X%.2f %s\n' % (stage_pos, self.speed_code))
        self.send(cmd)
        out = None
        while out is None:
            try:
                # controller should block reply until move complete.
                time.sleep(0.1)
                out = self.read()
            except TimeoutError:
                continue         
        return True, 'Move Complete'

    def close(self):
        self.comm.close()

    

class FTSAerotechAgent:
    """
    Agent for connecting to the FTS mirror control

    Args:
        ip_addr: IP address of Motion Controller
        port: Port of Motion Controller
        mode: 'acq': Start data acquisition on initialize
        samp: default sampling frequency in Hz
 
    """

    def __init__(self, agent, ip_addr, port, mode=None, samp=2):

        self.ip_addr = ip_addr
        self.port = int(port)

        self.stage = None
        self.initialized = False
        self.take_data = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        if mode == 'acq':
            self.auto_acq = True
        else:
            self.auto_acq = False
        self.sampling_frequency = float(samp)

        ### register the position feeds
        agg_params = {
            'frame_length' : 10*60, #[sec]
        }

        self.agent.register_feed('position',
                                 record = True,
                                 agg_params = agg_params,
                                 buffer_time = 0)

    def init_stage_task(self, session, params=None):
        """init_stage_task(params=None)
        Perform first time setup for communication with FTS stage.

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.
        """

        if params is None:
            params = {}
        
        if self.stage is not None and self.initialized:
            return True, 'Stages already Initialized'
           
        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already" \
                                "running".format(self.lock.job))
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")
            try:
                self.stage = FTSAerotechStage(self.ip_addr, self.port)
            except Exception as e:
                self.log.error(f"Error while connecting to FTS: {e}")
                reactor.callFromThread(reactor.stop)
                return False, "FTS Stage Initialization Failed"
        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq')
        return True, 'Stage Initialized.'

    def home_task(self, session, params=None):
        """ Home the stage to its negative limit
        """

        with self.lock.acquire_timeout(timeout=3, job='home') as acquired:
            if not acquired:
                self.log.warn("Could not start home because lock held by" \
                               f"{self.lock.job}")
                return False, "Could not get lock"
            try:
                self.stage.home()
            except Exception as e:
                self.log.error(f"Homing Failed: {e}")
                return False, "Homing Failed"
        return True, "Homing Complete"
    
    def move_to(self, session, params=None):
        """Move to absolute position relative to stage center (in mm)

        params: {'position':float between -74.8 and 74.8}
        """
        if params is None:
            return False, "No Position Given"
        if 'position' not in params:
            return False, "No Position Given"

        with self.lock.acquire_timeout(timeout=3, job='move') as acquired:
            if not acquired:
                self.log.warn("Could not start move because lock held by" \
                               f"{self.lock.job}")
                return False, "Could not get lock"
            return self.stage.move_to( params.get('position') )

        return False, "Move did not complete correctly?"
    
    def start_acq(self, session, params=None):
        """
        params:
            dict: {'sampling_frequency': float, sampling rate in Hz}

        The most recent position data is stored in session.data in the format::
            {"position":{"pos" : mirror position  }
        """
        if params is None:
            params = {}


        f_sample = params.get('sampling_frequency', self.sampling_frequency)
        pm = Pacemaker(f_sample, quantize=True)

        if not self.initialized or self.stage is None:
            raise Exception("Connection to Stages not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start acq because {self.lock.job} " \
                            "is already running")
                return False, "Could not acquire lock."

            self.log.info("Starting Data Acquisition for FTS Mirror at" \
                           f"{f_sample} Hz")
            session.set_status('running')
            self.take_data = True
            last_release = time.time()

            while self.take_data:
                if time.time()-last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=20):
                        self.log.warn("Could not re-acquire lock now held by" \
                                      f"{self.lock.job}.")
                        return False, "could not re-acquire lock"
                    last_release = time.time()
                pm.sleep()

                data = {
                    'timestamp':time.time(),
                    'block_name':'position',
                    'data':{}}
                success, pos = self.stage.get_position()
                if not success:
                    self.log.info("stage.get_position call failed")
                else:
                    data['data']['pos'] = pos
                    self.agent.publish_to_feed('position',data)

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        params:
            dict: {}
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
    pgroup.add_argument('--mode')
    pgroup.add_argument('--sampling_frequency')
    return parser


if __name__ == '__main__':

    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class = 'FTSAerotechAgent',
            parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    fts_agent = FTSAerotechAgent(agent, args.ip_address, args.port, 
                                args.mode, args.sampling_frequency)

    agent.register_task('init_stage', fts_agent.init_stage_task)
    agent.register_task('move_to', fts_agent.move_to)
    agent.register_task('home', fts_agent.home_task)

    agent.register_process('acq', fts_agent.start_acq, fts_agent.stop_acq)

    runner.run(agent, auto_reconnect=True)

