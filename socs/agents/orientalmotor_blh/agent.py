#!/usr/bin/env python3
'''OCS agent for BLH motor driver
'''
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.orientalmotor_blh.drivers import BLH

PORT_DEFAULT = '/dev/ttyACM0'
LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 100
INIT_TIMEOUT = 100


class BLHAgent:
    """OCS agent class for BLH motor driver

    Parameters
    ----------
    port : string
        Port to connect, default to /dev/ttyACM0
    """

    def __init__(self, agent, port=PORT_DEFAULT):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self._blh = BLH(port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('motor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)
        self.speed = 0.0

    @ocs_agent.param('_')
    def init_blh(self, session, params):
        """init_blh()

        **Task** - Initialize motor driver.
        """
        if self.initialized:
            return True, 'Already initialized'

        with self.lock.acquire_timeout(0, job='init_blh') as acquired:
            if not acquired:
                self.log.warn('Could not start init because '
                              '{} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock.'

            self._blh.connect()
            session.add_message('BLH initialized.')

        self.initialized = True

        return True, 'BLH module initialized.'

    @ocs_agent.param('sampling_frequency', default=2.5, type=float)
    def acq(self, session, params):
        """acq()

        **Process** - Monitor status of the motor.

        Parameters
        ----------
        sampling_frequency : float, optional
            Sampling frequency in Hz, defaults to 2.5 Hz

        Notes
        -----
        An example of the session data::

            >>> response.session['data']

            {'RPM': 0.0,
             'timestamp': 1736541796.779634
            }
        """
        f_sample = params['sampling_frequency']
        pace_maker = Pacemaker(f_sample)

        if not self.initialized:
            self.agent.start('init_blh')
            for _ in range(INIT_TIMEOUT):
                if self.initialized:
                    break
                time.sleep(0.1)

        if not self.initialized:
            return False, 'Could not initialize..'

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self.take_data = True
            session.data = {}
            last_release = time.time()

            while self.take_data:
                # Release lock
                if time.time() - last_release > LOCK_RELEASE_SEC:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=LOCK_RELEASE_TIMEOUT):
                        print(f'Re-acquire failed: {self.lock.job}')
                        return False, 'Could not re-acquire lock.'

                # Data acquisition
                current_time = time.time()
                data = {'timestamp': current_time, 'block_name': 'motor', 'data': {}}

                speed, error = self._blh.get_status()
                data['data']['RPM'] = speed
                data['data']['error'] = error
                self.speed = speed

                field_dict = {'RPM': speed, 'error': error}
                session.data.update(field_dict)

                self.agent.publish_to_feed('motor', data)
                session.data.update({'timestamp': current_time})

                pace_maker.sleep()

            self.agent.feeds['motor'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        self.agent.start('stop_rotation')
        while self.speed > 0.1:
            time.sleep(1)

        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    @ocs_agent.param('speed', default=None, type=int, check=lambda x: 50 <= x <= 3000)
    @ocs_agent.param('accl_time', default=None, type=float, check=lambda x: 0.5 <= x <= 15)
    @ocs_agent.param('decl_time', default=None, type=float, check=lambda x: 0.5 <= x <= 15)
    def set_values(self, session, params):
        """set_values(speed=None, accl_time=None, decl_time=None)

        **Task** - Set parameters for BLH motor driver.

        Parameters
        ----------
        speed : int, optional
            Motor rotation speed in RPM. Values must be in range [50, 3000].
        accl_time : float, optional
            Acceleration time. Values must be in range [0.5, 15]
        decl_time : float, optional
            Deceleration time. Values must be in range [0.5, 15]
        """
        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            speed = params['speed']
            accl_time = params['accl_time']
            decl_time = params['decl_time']

            if speed is not None:
                self._blh.set_speed(speed)

            if accl_time is not None:
                self._blh.set_accl_time(accl_time, accl=True)

            if decl_time is not None:
                self._blh.set_accl_time(decl_time, accl=False)

        return True, 'Set values for BLH'

    @ocs_agent.param('forward', default=True, type=bool)
    def start_rotation(self, session, params):
        """start_rotation(forward=True)

        **Task** - Start motor rotation.

        Parameters
        ----------
        forward : bool, default True
            Move forward if True
        """
        if not self.take_data:
            self.agent.start('acq')
            for _ in range(ACQ_TIMEOUT):
                if self.take_data:
                    break
                time.sleep(0.1)

        if not self.take_data:
            return False, 'Could not start acq.'

        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            if not self.take_data:
                return False, 'acq is not currently running.'

            forward = params.get('forward')
            if forward is None:
                forward = True

            result = self._blh.start(forward=forward)
            if not result:
                return False, 'Could not start rotation.'

        return True, 'BLH rotation started.'

    @ocs_agent.param('_')
    def stop_rotation(self, session, params):
        """stop_rotation()

        **Task** - Stop motor rotation.
        """
        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            result = self._blh.stop()
            if not result:
                return False, 'Could not stop rotation.'

        return True, 'BLH rotation stop command was published.'

    @ocs_agent.param('_')
    def clear_alarm(self, session, params):
        """clear_alarm()

        **Task** - Clear alarm of the driver.
        """
        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start clear_alarm because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self._blh.clear_alarm()
            _, error = self._blh.get_status()
            if error != 0:
                return False, 'Could not clear alarm.'

        return True, 'Alarm clear command was published.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=PORT_DEFAULT)

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = make_parser()
    args = site_config.parse_args(agent_class='BLHAgent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)

    blh_agent = BLHAgent(agent_inst, port=args.port)

    agent_inst.register_task(
        'set_values',
        blh_agent.set_values
    )

    agent_inst.register_task(
        'start_rotation',
        blh_agent.start_rotation
    )

    agent_inst.register_task(
        'stop_rotation',
        blh_agent.stop_rotation
    )

    agent_inst.register_task(
        'init_blh',
        blh_agent.init_blh
    )

    agent_inst.register_task(
        'clear_alarm',
        blh_agent.clear_alarm
    )

    agent_inst.register_process(
        'acq',
        blh_agent.acq,
        blh_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
