import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    # yes I shouldn't have named that module agent
    from xy_agent.xy_connect import XY_Stage


class LATRtXYStageAgent:
    """
    Agent for connecting to the LATRt XY Stages.

    Args:
        ip_addr: IP address where RPi server is running.
        port: Port the RPi Server is listening on.
        mode: 'acq': Start data acquisition on initialize.
        samp: Default sampling frequency in Hz.
    """

    def __init__(self, agent, ip_addr, port, mode=None, samp=2):

        self.ip_addr = ip_addr
        self.port = int(port)

        self.xy_stage = None
        self.initialized = False
        self.take_data = False
        self.is_moving = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        if mode == 'acq':
            self.auto_acq = True
        else:
            self.auto_acq = False
        self.sampling_frequency = float(samp)

        # register the position feeds
        agg_params = {
            'frame_length': 10 * 60,  # [sec]
        }

        self.agent.register_feed('positions',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('_')
    def init_xy_stage(self, session, params=None):
        """init_xy_stage()

        **Task** - Perform first time setup for communication with XY stages.

        """

        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")

            self.xy_stage = XY_Stage(self.ip_addr, self.port)
            self.xy_stage.init_stages()
            print("XY Stages Initialized")

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True
        if self.auto_acq:
            self.agent.start('acq', params={'sampling_frequency': self.sampling_frequency})
        return True, 'XY Stages Initialized.'

    @ocs_agent.param('distance', type=float)
    @ocs_agent.param('velocity', type=float, check=lambda x: 0 <= x < 1.2)
    def move_x_cm(self, session, params):
        """move_x_cm(distance, velocity)

        **Task** - Move the X axis.

        Parameters:
            distance (float): Distance to move in cm.
            velocity (float): Velocity to move at. Must be less than 1.2.

        """

        with self.lock.acquire_timeout(timeout=3, job='move_x_cm') as acquired:
            if not acquired:
                self.log.warn(f"Could not start x move because lock held by {self.lock.job}")
                return False
            self.xy_stage.move_x_cm(params.get('distance', 0), params.get('velocity', 1))

        time.sleep(1)
        while True:
            # data acquisition updates the moving field if it is running
            if not self.take_data:
                with self.lock.acquire_timeout(timeout=3, job='move_x_cm') as acquired:
                    if not acquired:
                        self.log.warn(f"Could not check because lock held by {self.lock.job}")
                        return False, "Could not acquire lock"
                    self.is_moving = self.xy_stage.moving

            if not self.is_moving:
                break
        return True, "X Move Complete"

    @ocs_agent.param('distance', type=float)
    @ocs_agent.param('velocity', type=float, check=lambda x: 0 <= x < 1.2)
    def move_y_cm(self, session, params):
        """move_y_cm(distance, velocity)

        **Task** - Move the Y axis.

        Parameters:
            distance (float): Distance to move in cm.
            velocity (float): Velocity to move at. Must be less than 1.2.

        """

        with self.lock.acquire_timeout(timeout=3, job='move_y_cm') as acquired:
            if not acquired:
                self.log.warn(f"Could not start y move because lock held by {self.lock.job}")
                return False, "could not acquire lock"
            self.xy_stage.move_y_cm(params.get('distance', 0), params.get('velocity', 1))

        time.sleep(1)
        while True:
            # data acquisition updates the moving field if it is running
            if not self.take_data:
                with self.lock.acquire_timeout(timeout=3, job='move_y_cm') as acquired:
                    if not acquired:
                        self.log.warn(f"Could not check for move because lock held by {self.lock.job}")
                        return False, "could not acquire lock"
                    self.is_moving = self.xy_stage.moving
            if not self.is_moving:
                break
        return True, "Y Move Complete"

    @ocs_agent.param('position', type=tuple)
    def set_position(self, session, params):
        """set_position(position)

        **Task** - Set position of the XY stage.

        Parameters:
            position (tuple): (X, Y) position.

        """
        with self.lock.acquire_timeout(timeout=3, job='set_position') as acquired:
            if not acquired:
                self.log.warn(f"Could not set position because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.xy_stage.position = params['position']
        return True, "Position Updated"

    @ocs_agent.param('_')
    def set_enabled(self, session, params=None):
        """set_enabled()

        **Task** - Tell the controller to hold stages enabled.

        """
        with self.lock.acquire_timeout(timeout=3, job='set_enabled') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set position because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.xy_stage.enable()
        return True, "Enabled"

    @ocs_agent.param('_')
    def set_disabled(self, session, params=None):
        """set_disabled()

        **Task** - Tell the controller to hold stages disabled.

        """
        with self.lock.acquire_timeout(timeout=3, job='set_disabled') as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set position because lock held by {self.lock.job}")
                return False, "Could not acquire lock"

            self.xy_stage.disable()
        return True, "Disabled"

    @ocs_agent.param('sampling_frequency', default=None, type=float)
    def acq(self, session, params=None):
        """acq(sampling_frequency=2)

        **Process** - Run data acquisition.

        Parameters:
            sampling_frequency (float): Sampling rate to acquire data at.
                Defaults to value set in site config file (or 2 Hz if
                unspecified.)

        Notes:
            The most recent positions are stored in the session.data object in the
            format::

                >>> response.session['data']
                {"positions":
                    {"x": x position in cm,
                     "y": y position in cm}
                }

        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', self.sampling_frequency)
        pm = Pacemaker(f_sample, quantize=True)

        if not self.initialized or self.xy_stage is None:
            raise Exception("Connection to XY Stages not initialized")

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.log.info(f"Starting Data Acquisition for XY Stages at {f_sample} Hz")
            self.take_data = True
            last_release = time.time()

            while self.take_data:
                if time.time() - last_release > 1.:
                    if not self.lock.release_and_acquire(timeout=10):
                        self.log.warn(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False, "could not re-acquire lock"
                    last_release = time.time()
                pm.sleep()

                data = {'timestamp': time.time(), 'block_name': 'positions', 'data': {}}
                pos = self.xy_stage.position
                self.is_moving = self.xy_stage.moving

                data['data']['x'] = pos[0]
                data['data']['y'] = pos[1]

                self.agent.publish_to_feed('positions', data)
                session.data.update(data['data'])
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
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


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class='LATRtXYStageAgent',
                                  parser=parser,
                                  args=args)
    agent, runner = ocs_agent.init_site_agent(args)

    xy_agent = LATRtXYStageAgent(agent, args.ip_address, args.port, args.mode, args.sampling_frequency)

    agent.register_task('init_xy_stage', xy_agent.init_xy_stage)
    agent.register_task('move_x_cm', xy_agent.move_x_cm)
    agent.register_task('move_y_cm', xy_agent.move_y_cm)
    agent.register_task('set_position', xy_agent.set_position)

    agent.register_process('acq', xy_agent.acq, xy_agent._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
