import argparse
import os
import time

import numpy as np
import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock
from twisted.internet import reactor

from socs.agents.galildmc_axis_controller.drivers import GalilAxis


class GalilAxisControllerAgent:
    """ Agent to connect to galil linear stage motors for SAT coupling optics for passband measurements on-site.

    Args:
        ip (str): 
            IP address for the Galil Stage Motor Controller
        config-file (str): 
            .toml config file for initializing hardware axes
        port (int, optional): 
            TCP port to connect, default is 23
        configfile (str, optional):
            Path to a GalilDMC axis config file. This will be loaded by `input_configfile` 
            by default
    """

    def __init__(self, agent, ip, configfile, port=23):
        self.lock = TimeoutLock()
        self.agent = agent
        self.log = agent.log
        self.ip = ip
        self.port = port
        self.configfile = configfile

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
            self.stage = GalilAxis(self.ip, self.port, self.configfile)
            # print('self.ip is ', self.ip)
            # print('self.configfile is', self.configfile)

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

            pm = Pacemaker(1)  # , quantize=True)
            while self.take_data:
                pm.sleep()
                # Reliqinuish sampling lock occassionally
                if time.time() - last_release > 1:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Failed to re-acquire sampling lock, "
                                      f"currently held by {self.lock.job}.")
                        continue

                try:
                    data = self.stage.get_data()
                    print('get_data in acq:', data)
                    self.log.debug("{data}", data=session.data)
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from galil stage controller. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue

                session.data = {"fields": data,
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


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('lindist', type=float)
    def move_relative_linearpos(self, session, params):
        """set_relative_linearpos(axis, lindist)

        **Task** - Move axis stage in linear +/- direction for a specified axis
        and distance.

        Parameters:
            axis (str): Axis to set the linear distance for. Ex: 'A'
            lindist (int): Specified linear distance in millimeters (mm)

        Note:
            The use of `set_linear` vs `set_angular` is important as the
            conversion values for turning mm to encoder counts is different
            from the conversion value for turning degrees to encoder counts.
            Be sure NOT to use this task if you want to move in angular distance.
        """
        axis = params['axis']
        dist = params['lindist']
        with self.lock.acquire_timeout(0, job='move_relative_linearpos') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_relative_linearpos(axis, dist)
            value, units = self.stage.query_relative_position(axis=axis, movetype='linear')
            session.add_message(f'{axis} set to relative linear position: {value}{units}')
            
            # setting the conditions for beginning motion 
            if value == dist:
                self.stage.begin_motion(axis)
                self.log.info(f'Starting motion to {dist}{units}')
            else:
                self.log.info(f"{axis} position mismatch: expected {dist} {units}, got {value} {units}.")

    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('angdist', type=float)
    def move_relative_angpos(self, session, params):
        """move_relative_angpos(axis, angdist)

        **Task** - Move axis stage in linear +/- direction for a specified axis
        and distance.

        Parameters:
            axis (str): Axis to set the linear distance for. Ex: 'A'
            angdist (int): Specified angular distance in degrees

        Note:
            The use of `move_linear` vs `move_angular` is important as the
            conversion values for turning mm to encoder counts is different
            from the conversion value for turning degrees to encoder counts.
            Be sure NOT to use this task if you want to move in angular distance.
        """
        axis = params['axis']
        dist = params['angdist']
        with self.lock.acquire_timeout(timeout=3, job='move_relative_angpos') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_angular(axis, dist)
            time.sleep(0.5)
            value, units = self.stage.set_relative_angularpos(axis=axis, angdist=dist)
            session.add_message(f'{axis} set to relative angular position: {value}{units}')

            if value == dist:
                self.stage.begin_motion(axis)
                self.log.info(f'Starting motion to {dist}{units}')
            else:
                self.log.info(f"{axis} position mismatch: expected {dist} {units}, got {value} {units}.")

        return True, f'Set {axis} to {dist}'


# TODO: absolute position for linear and angular
# TODO: add a second choice to get brak status param decorator for the ability to query all brake statuses at once
    @ocs_agent.param('axis', type=str)
    def get_brake_status(self, session, params):
        """get_brake_status()

        **Task** - Query brakes status for all 4 axess

        """
        with self.lock.acquire_timeout(timeout=5, job='get_brake_status') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            response = self.stage.get_brake_status()
            session.add_message(str(response))

        return True, 'Queried brake status'


    @ocs_agent.param('axis', type=str)
    def release_axis_brake(self, session, params):
        """release_axis_brake(axis)

        **Task** - Releases the brake for specified axis

        Parameters:
            axis (str): Specified axis for releasing brake. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='release_axis_brake') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.release_brake(axis)
            new_response = self.stage.query_brake_status()
            new_brake_status = new_response[axis]['status']
            self.log.info(f'Brake now set to {new_brake_status}')

        return True, f'Commanded brake to {new_brake_status} for {axis}.'


    @ocs_agent.param('axis', type=str)
    def engage_axis_brake(self, session, params):
        """engage_axis_brake(axis)

        **Task** - Engages the brake for specified axis

        Parameters:
            axis (str): Specified axis for releasing brake. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='engage_axis_brake') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.engage_brake(axis)
            new_response = self.stage.query_brake_status()
            new_brake_status = new_response[axis]['status']
            self.log.info(f'Brake now set to {new_brake_status}')

        return True, f'Commanded brake to {new_brake_status} for {axis}.'



    @ocs_agent.param('configfile', type=str, default=None)
    def input_configfile(self, session, params=None):
        """input_configfile(configfile=None)

        **Task** Upload GalilDMC Axis Controller configuration file to initialize device
        and axes on device

        Parameters:
            configfile (str, optional):
                name of .yaml config file. Defaults to the fite set in the site config


        """

        configfile = params['configfile']
        if configfile is None:
            configfile = self.configfile
        if configfile is None:
            raise ValueError("No configfile specified")
        configfile = os.path.join(os.environ['OCS_CONFIG_DIR'], configfile)

        with self.lock.acquire_timeout(job='input_configfile') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self._lock.job} is already running")
                return False, "Could not acquire lock"

            with open(configfile) as f:
                config = yaml.safe_load(f)
            
            axes = list(config['galil']['motorconfigparams'].keys())
            
            for a in axes:
                # set motor type
                motortype = config['galil']['motorconfigparams'][a]['MT']
                self.stage.set_motor_type(a, type=motortype)

                # disable off on error
                errtype = config['galil']['motorconfigparams'][a]['OE']
                errtype = int(errtype)
                if errtype == 0:
                    self.stage.disable_off_on_error(a)

                # set amp gain
                gn = config['galil']['motorconfigparams'][a]['AG']
                self.stage.set_amp_gain(a, val=gn)

                # set torque limit
                tl = config['galil']['motorconfigparams'][a]['TL']
                self.stage.set_torque_limitn(a, val=tl)

                # set current loop gain
                clgn = config['galil']['motorconfigparams'][a]['AU']
                self.stage.set_amp_currentloop_gain(a, val=clgn)

                # enable sin commutation
                initstate = config['galil']['initaxisparams']['BA']
                if initstate == 'True':
                    # enable sin commutation
                    stage.enable_sin_commutation(a)
                    # set magnetic cycle
                    mag = config['galil']['initaxisparams']['BM']
                    stage.set_magnetic_cycle(a, val=mag)
                    # initialize 
                    stage.initialize_axis(a)


            



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
    args = site_config.parse_args(agent_class='GalilAxisControllerAgent',
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
    galilaxis_agent = GalilAxisControllerAgent(agent, args.ip, args.port)
    agent.register_task('init', galilaxis_agent.init, startup=init_params)
    agent.register_task('move_relative_linear', galilaxis_agent.move_relative_linear)
    agent.register_task('move_relative_angular', galilaxis_agent.move_relative_angular)
    agent.register_task('get_brake_status', galilaxis_agent.get_brake_status)
    agent.register_task('release_axis_brake', galilaxis_agent.release_axis_brake)
    agent.register_task('engage_axis_brake', galilaxis_agent.engage_axis_brake)
    agent.register_task('input_configfile', galilaxis_agent.input_configfile)
    agent.register_process('acq', galilaxis_agent.acq, galilaxis_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
