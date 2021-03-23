import time
import os
import socket
import argparse
from Pfeiffer_Turbo_Controller_Driver import Pfeiffer_Turbo_Controller

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class PfeifferTurboControllerAgent:
    def __init__(self, agent, ip_address, port_number, turbo_address):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.port_number = port_number
        self.turbo_address = turbo_address
        self.monitor = False

        self.turbo = None

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 10*60,
        }
        self.agent.register_feed('pfeiffer_turbo',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def init_turbo(self, session, params=None):
        """ Task to connect to the turbo controller"""

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.turbo = Pfeiffer_Turbo_Controller(self.ip_address, self.port_number, self.turbo_address)
                #self.idn = self.psu.identify()
            except socket.timeout as e:
                self.log.error("Turbo Controller timed out during connect")
                return False, "Timeout"
            self.log.info("Connected to turbo controller")
            
                                  
        # Start data acquisition if requested in site-config
        auto_acquire = params.get('auto_acquire', False)
        print(f"auto acquire is {auto_acquire}")
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Initialized Turbo Controller.'

    def monitor_turbo(self, session, params=None):
        """
            Process to continuously monitor turbo motor temp and rotation speed and
            send info to aggregator.

            Args:
                wait (float, optional):
                    time to wait between measurements [seconds].
        """
        if params is None:
            params = {}

        wait_time = params.get('wait', 1)

        self.monitor = True

        while self.monitor:
            with self.lock.acquire_timeout(1) as acquired:
                if acquired:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'turbo_output',
                        'data': {}
                    }
                    
                    try:    
                        data['data']["Turbo_Motor_Temp"] = self.turbo.get_turbo_motor_temperature()
                        data['data']["Rotation_Speed"] = self.turbo.get_turbo_actual_rotation_speed()
                    
                    except ValueError as e:
                        self.log.error(e)
                        
                    # self.log.info(str(data))
                    # print(data)
                    self.agent.publish_to_feed('pfeiffer_turbo', data)

                    # Allow this process to be queried to return current data
                    session.data = data

                else:
                    self.log.warn("Could not acquire in monitor turbo")

            time.sleep(wait_time)

        return True, "Finished monitoring turbo"

    def stop_monitoring(self, session, params=None):
        """Stop monitoring the turbo output."""
        if self.monitor:
            self.monitor = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    def turn_turbo_on(self, session, params=None):
        """Turns the turbo on."""

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.turbo.ready_turbo()
                time.sleep(1)
                self.turbo.turn_turbo_motor_on()
            else:
                return False, "Could not acquire lock"

        return True, 'Turned Turbo Motor On.'
    
    def turn_turbo_off(self, session, params=None):
        """Turns the turbo off."""

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.turbo.turn_turbo_motor_off()
                time.sleep(1)
                self.turbo.unready_turbo()
            else:
                return False, "Could not acquire lock"

        return True, 'Turned Turbo Motor Off.'
                          
    def get_turbo_error_code(self, session, params=None):
        """
        Gets the turbos error code (if there is one) and publishes the code.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
    
                error_code = self.turbo.get_turbo_error_code()

                data = {'timestamp': time.time(),
                        'block_name': "turbo_error_code",
                        'data': {'turbo_error_code': int(error_code)}
                        }
                self.agent.publish_to_feed('pfeiffer_turbo', data)
                session.data = data

            else:
                return False, "Could not acquire lock"

        return True, f"error is {error_code}"

    def acknowledge_turbo_errors(self, session, params=None):
        """
        Sends an acknowledgment of the error code to the turbo.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.turbo.acknowledge_turbo_errors()
            else:
                return False, "Could not acquire lock"

        return True, 'Acknowledged Turbo Errors.'

if __name__ == '__main__':
    parser = site_config.add_arguments()

    # Add options specific to this agent.

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--port-number')
    pgroup.add_argument('--turbo-address')

    # Parse comand line.
    args = parser.parse_args()
    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Pfeiffer Turbo Controller')
                          
    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = PfeifferTurboControllerAgent(agent, 
                                     args.ip_address, 
                                     int(args.port_number), 
                                     int(args.turbo_address))

    agent.register_task('init', p.init_turbo, startup=init_params)
    agent.register_task('turn_turbo_on', p.turn_turbo_on)
    agent.register_task('turn_turbo_off', p.turn_turbo_off)
    agent.register_task('get_turbo_error_code', p.get_turbo_error_code)
    agent.register_task('acknowledge_turbo_errors', p.acknowledge_turbo_errors)
    agent.register_process('acq', p.monitor_turbo, p.stop_monitoring)
                          
    runner.run(agent, auto_reconnect=True)