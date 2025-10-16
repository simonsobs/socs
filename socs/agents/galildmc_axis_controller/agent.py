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

# TODO: update docstrings
# TODO: check jobs in each task to match name of task
# TODO Tasks: get_relative_position

class GalilAxisControllerAgent:
    """ Agent for controlling Galil axis motors used in SAT
    coupling optics instrument for passband measurements on-site.

    Args:
        ip (str): IP address for the Galil axis motor controller
        config-file (str): Path to .yaml file config file for initializing motor 
            and axis settings
        port (int, optional): TCP port to connect, Default is 23
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

        **Task** - Initalize connection to Galil axis controller.

        Parameters:
            auto_acquire(bool):  If True, start acquisition immediately after
            initialization. Defaults to False.

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

            # test connection
            try:
                self.stage.get_data()
            except ConnectionError:
                self.log.error("Could not establish connection to galil axis motor controller")
                return False, "Galil Axis Controller agent initialization failed"

        self.initialized = True

        # start data acquistion if requested
        if params['auto_acquire']:
            resp = self.agent.start('acq', params={})
            self.log.info(f'Response from acq.start(): {resp[1]}')

        return True, "Galil Axis Controller agent initialized"

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq()

        **Process** - Starts acquisition of data from the Galil Stage Controller.

        Parameters:
            test_mode (bool, optional): Run the process loop only once.
                This is meant only for testing. Default is False.

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
    def set_relative_linearpos(self, session, params):
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
        with self.lock.acquire_timeout(0, job='set_relative_linearpos') as acquired:
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
    def set_relative_angpos(self, session, params):
        """set_relative_angpos(axis, angdist)

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
        with self.lock.acquire_timeout(timeout=3, job='set_relative_angpos') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_relative_angularpos(axis=axis, angdist=dist)

        return True, f'Set {axis} to move by {dist} degrees.'


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('angpos', type=float)
    def set_absolute_angpos(self, session, params):
        """set_absolute_angpos(axis, angpos)

        **Task** - Move axis stage in linear +/- direction for a specified axis
        and distance.

        Parameters:
            axis (str): Axis to set the linear distance for. Ex: 'A'
            angpos (int): Specified angular distance in degrees

        """
        axis = params['axis']
        angpos = params['angpos']
        with self.lock.acquire_timeout(timeout=3, job='set_absolute_angpos') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_absolute_angularpos(axis=axis, pos=angpos)

        return True, f'Set {axis} to go to {angpos} degrees.'


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('linpos', type=float)
    def set_absolute_linearpos(self, session, params):
        """set_absolute_linearpos(axis, linpos)

        **Task** - Move axis stage in linear +/- direction for a specified axis
        and distance.

        Parameters:
            axis (str): Axis to set the linear distance for. Ex: 'A'
            linpos (int): Specified angular distance in degrees

        """
        axis = params['axis']
        linpos = params['linpos']
        with self.lock.acquire_timeout(timeout=3, job='set_absolute_linearpos') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_absolute_linearpos(axis=axis, pos=linpos)

        return True, f'Set {axis} to go to {linpos} mm.'


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



    @ocs_agent.param('axis', type=str)
    def begin_axis_motion(self, session, params):
        """begin_axis_motion(axis)

        **Task** - Moves the axis specified.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='begin_axis_motion') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.begin_motion(axis)
            self.log.info(f'Now moving {axis}')

        return True, f'Commanded {axis} to move.'


    # TODO: add choices for motortype?
    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('motortype', type=int)
    def set_motortype(self, session, params):
        """set_motortype(axis)

        **Task** - Sets motor type for each axis, depending on servo motor features

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        motortype = params['motortype'] 
        with self.lock.acquire_timeout(timeout=5, job='set_motortype') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_motortype(axis, motortype)
            self.log.info(f'Motor type for {axis} set to {movetype}')

        return True


    @ocs_agent.param('axis', type=str)
    def disable_off_on_error(self, session, params):
        """disable_off_on_error(axis)

        **Task** - Disables the off-on-error function for the specified axis, 
        preventing the controller from shutting off motor commands in response to
        position errors

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='disable_off_on_error') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.disable_off_on_error(axis)
            self.log.info(f'Off-on-error for {axis} disabled')

        return True


    # TODO, add default value for val
    # TODO: finish the docstring
    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_amp_gain(self, session, params):
        """set_amp_gain(axis, val)

        **Task** - Set amplifier gain for internal amplifier per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_amp_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_amp_gain(axis, val)
            self.log.info(f'Amp gain for {axis} set to {val}')

        return True


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_torque_limit(self, session, params):
        """set_torque_limit(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): voltage  

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_torque_limit') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_torque_limit(axis, val)
            self.log.info(f'Torque limit for {axis} set to {val} volts')

        return True


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_amp_currentloop_gain(self, session, params):
        """set_amp_currentloop_gain(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_amp_currentloop_gain') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_amp_currentloop_gain(axis, val)
            self.log.info(f'Torque limit for {axis} set to {val}')

        return True

    # TODO: fix the docstring
    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def set_magnetic_cycle(self, session, params):
        """set_magnetic_cycle(axis, val)

        **Task** - Set motor torque limit per axis.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='set_magnetic_cycle') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_magnetic_cycle(axis, val)
            self.log.info(f'Magnetic cycle for {axis} set to {val}')

        return True

    
    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def initialize_axis(self, session, params):
        """initialize_axis(axis, val)

        **Task** - Initialize axes for sinusoidal amplifier settings..

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='initialize_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.initialize_axis(axis, val)
            self.log.info(f'Initialized {axis} to {val} setting')

        return True

    
    # TODO: add the default setting for zero cus it's used for homing
    # TODO: docstrings
    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('val', type=float)
    def define_position(self, session, params):
        """define_position(axis, val)

        **Task** - Resets the position of an axis encoder to a specifically
            set value.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        val = params['val']
        with self.lock.acquire_timeout(timeout=5, job='define_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.define_position(axis, val)
            self.log.info(f'{axis} position now set to {val}')

        return True


    @ocs_agent.param('axis', type=str)
    @ocs_agent.param('speed', type=float)
    def jog_axis(self, session, params):
        """jog_axis(axis, val)

        **Task** - Resets the position of an axis encoder to a specifically
            set value.

        Parameters:
            axis (str): Specified axis. Ex. 'A'
            val (float): 

        """
        axis = params['axis']
        speed = params['speed']
        with self.lock.acquire_timeout(timeout=5, job='jog_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.jog_axis(axis, speed)
            self.log.info(f"{axis}'s speed is now set to {speed}")

        return True

    # TODO: docstrings
    @ocs_agent.param('axis', type=str)
    def enable_axis(self, session, params):
        """enable_axis(axis)

        **Task** - Resets the position of an axis encoder to a specifically
            set value.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='enable_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.enable_axis(axis)
            self.log.info(f"{axis} is enabled.")

        return True


    # TODO: docstrings
    @ocs_agent.param('axis', type=str)
    def disable_axis(self, session, params):
        """disable_axis(axis)

        **Task** - Resets the position of an axis encoder to a specifically
            set value.

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='disable_axis') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.disable_axis(axis)
            self.log.info(f"{axis} is disabled.")

        return True

    @ocs_agent.param('axis', type=str)
    def enable_sin_commutation(self, session, params):
        """enable_sin_commutation(axis)

        **Task** - Enable the sin commutation for the sinusoidal amplifier per axis

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='enable_sin_commutation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.enable_sin_commutation(axis)
            self.log.info(f'Sin commutation setting for {axis} is enabled.')

        return True


   # TODO: docstrings 
    @ocs_agent.param('axis', type=str)
    def disable_limit_switch(self, session, params):
        """disable_limit_switch(axis)

        **Task** - Enable the sin commutation for the sinusoidal amplifier per axis

        Parameters:
            axis (str): Specified axis. Ex. 'A'

        """
        axis = params['axis']
        with self.lock.acquire_timeout(timeout=5, job='disable_limit_switch') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.disable_limit_switch(axis)
            self.log.info(f'Limit switch for {axis} is disabled.')

        return True


   # TODO: docstrings, add default setting 
    @ocs_agent.param('polarity', type=int)
    def set_limitswitch_polarity(self, session, params):
        """set_limitswitch_polarity()

        **Task** - ??

        """
        pol = params['polarity']
        with self.lock.acquire_timeout(timeout=5, job='set_limitswitch_polarity') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_limitswitch_polarity(pol)
            self.log.info(f'Limit switch polarity for {axis} is set to {pol}.')

        return True

    
   # TODO: docstrings, add default setting if axis is NOne 
    @ocs_agent.param('axis', type=str)
    def stop_axis_motion(self, session, params):
        """stop_axis_motion()

        **Task** - ??

        """
        pol = params['polarity']
        with self.lock.acquire_timeout(timeout=5, job='stop_axis_motion') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.stop_motion(axis)
            self.log.info(f'Stopped motion for {axis}.')

        return True


    # TODO: add the default setting for zero cus it's used for homing
    # TODO: docstrings
    @ocs_agent.param('order', type=str)
    def set_gearing(self, session, params):
        """set_gearing(order)

        **Task** - ??.

        Parameters:
            order (str): 

        """
        order = params['order']
        with self.lock.acquire_timeout(timeout=5, job='set_gearing') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_gearing(order)
            self.log.info(f'Gearing set to {order}')

        return True


    @ocs_agent.param('order', type=str)
    def set_gearing_ratio(self, session, params):
        """set_gearing_ratio(order)

        **Task** - ??.

        Parameters:
            order (str): 

        """
        order = params['order']
        with self.lock.acquire_timeout(timeout=5, job='set_gearing_ratio') as acquired:
            if not acquired:
                self.log.warn(f"Could not start Task because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            self.stage.set_gearing_ratio(order)
            self.log.info(f'Gearing ratio set to {order}')

        return True


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
                self.stage.set_motor_type(axis=a, motortype=motortype)

                # disable off on error
                errtype = config['galil']['motorconfigparams'][a]['OE']
                errtype = int(errtype)
                if errtype == 0:
                    self.stage.disable_off_on_error(axis=a)

                # set amp gain
                gn = config['galil']['motorconfigparams'][a]['AG']
                self.stage.set_amp_gain(axis=a, val=gn)

                # set torque limit
                tl = config['galil']['motorconfigparams'][a]['TL']
                self.stage.set_torque_limitn(axis=a, val=tl)

                # set current loop gain
                clgn = config['galil']['motorconfigparams'][a]['AU']
                self.stage.set_amp_currentloop_gain(axis=a, val=clgn)

                # enable sin commutation
                initstate = config['galil']['initaxisparams']['BA']
                if initstate == 'True':
                    # enable sin commutation
                    self.stage.enable_sin_commutation(axis=a)
                    # set magnetic cycle
                    mag = config['galil']['initaxisparams']['BM']
                    self.stage.set_magnetic_cycle(axis=a, val=mag)
                    # initialize 
                    self.stage.initialize_axis(axis=a)


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
    agent.register_task('set_relative_linearpos', galilaxis_agent.set_relative_linearpos)
    agent.register_task('set_absolute_linearpos', galilaxis_agent.set_absolute_linearpos)
    agent.register_task('set_relative_angpos', galilaxis_agent.set_relative_angpos)
    agent.register_task('set_absolute_angpos', galilaxis_agent.set_absolut_angpos)
    agent.register_task('get_brake_status', galilaxis_agent.get_brake_status)
    agent.register_task('release_axis_brake', galilaxis_agent.release_axis_brake)
    agent.register_task('engage_axis_brake', galilaxis_agent.engage_axis_brake)
    agent.register_task('begin_axis_motion', galilaxis_agent.begin_axis_motion)
    agent.register_task('stop_axis_motion', galilaxis_agent.stop_axis_motion)
    agent.register_task('set_motortype', galilaxis_agent.set_motortype)
    agent.register_task('disable_off_on_error', galilaxis_agent.disable_off_on_error)
    agent.register_task('set_amp_gain', galilaxis_agent.set_amp_gain)
    agent.register_task('set_torque_limit', galilaxis_agent.set_torque_limit)
    agent.register_task('set_amp_currentloop_gain', galilaxis_agent.set_amp_currentloop_gain)
    agent.register_task('set_magnetic_cycle', galilaxis_agent.set_magnetic_cycle)
    agent.register_task('initialize_axis', galilaxis_agent.initialize_axis)
    agent.register_task('define_position', galilaxis_agent.define_position)
    agent.register_task('jog_axis', galilaxis_agent.jog_axis)
    agent.register_task('enable_axis', galilaxis_agent.enable_axis)
    agent.register_task('enable_sin_commutation', galilaxis_agent.enable_sin_commutation)
    agent.register_task('disable_axis', galilaxis_agent.disable_axis)
    agent.register_task('disable_limit_switch', galilaxis_agent.disable_limit_switch)
    agent.register_task('set_limitswitch_polarity', galilaxis_agent.set_limitswitch_polarity)
    agent.register_task('set_gearing', galilaxis_agent.set_gearing)
    agent.register_task('set_gearing_ratio', galilaxis_agent.set_gearing_ratio)
    agent.register_task('input_configfile', galilaxis_agent.input_configfile)
    agent.register_process('acq', galilaxis_agent.acq, galilaxis_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
