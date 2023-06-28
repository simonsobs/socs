#!/usr/bin/env python3
'''OCS agent for BLE2 motor driver
'''
import time
import os
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.agent.ble2 import BLE2

PORT_DEFAULT = '/dev/ttyACM0'
LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 100
INIT_TIMEOUT = 100

class BLE2Agent:
    '''OCS agent class for BLE2 motor driver
    '''
    def __init__(self, agent, port=PORT_DEFAULT):
        '''
        Parameters
        ----------
        port : string
            Port to connect
        '''
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self._ble2 = BLE2(port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('motor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def init_ble2(self, session, params=None):
        '''Initialization of BLE2 motor driver'''
        if self.initialized:
            return True, 'Already initialized'

        with self.lock.acquire_timeout(0, job='init_ble2') as acquired:
            if not acquired:
                self.log.warn('Could not start init because '
                              '{} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock.'

            session.set_status('starting')

            self._ble2.connect()
            session.add_message('BLE2 initialized.')

        self.initialized = True

        return True, 'BLE2 module initialized.'


    def start_acq(self, session, params):
        '''Starts acquiring data.
        '''
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', 2.5)
        sleep_time = 1/f_sample - 0.1

        if not self.initialized:
            self.agent.start('init_ble2')
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

            session.set_status('running')

            self.take_data = True
            session.data = {"fields": {}}
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
                data = {'timestamp':current_time, 'block_name':'motor', 'data':{}}

                speed = self._ble2.get_status()
                data['data']['RPM'] = speed

                field_dict = {f'motor': {'RPM': speed}}
                session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('motor', data)
                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['motor'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    def set_values(self, session, params=None):
        '''A task to set parameters for BLE2 motor driver

        Parameters
        ----------
        speed : int
            Motor rotation speed in RPM
        accl_time : float
            Acceleration time
        decl_time : float
            Deceleration time
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            speed = params.get('speed')
            if not speed is None:
                self._ble2.set_speed(speed)

            accl_time = params.get('accl_time')
            if not accl_time is None:
                self._ble2.set_accl_time(accl_time, accl=True)

            decl_time = params.get('decl_time')
            if not decl_time is None:
                self._ble2.set_accl_time(decl_time, accl=False)

        return True, f'Set values for BLE2'

    def start_rotation(self, session, params=None):
        '''Start rotation

        Parameters
        ----------
        forward : bool, default True
            Move forward if True
        '''
        if params is None:
            params = {}

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

            self._ble2.start(forward=forward)

        return True, f'BLE2 rotation started.'

    def stop_rotation(self, session, params=None):
        '''Stop rotation'''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self._ble2.stop()

        return True, f'BLE2 rotation stop command was published.'


def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()

    args = parser.parse_args()
    site_config.reparse_args(args, 'BLE2Agent')

    agent_inst, runner = ocs_agent.init_site_agent(args)

    ble2_agent = BLE2Agent(agent_inst)

    agent_inst.register_task(
        'set_values',
        ble2_agent.set_values
    )

    agent_inst.register_task(
        'start_rotation',
        ble2_agent.start_rotation
    )

    agent_inst.register_task(
        'stop_rotation',
        ble2_agent.stop_rotation
    )

    agent_inst.register_task(
        'init_ble2',
        ble2_agent.init_ble2
    )

    agent_inst.register_process(
        'acq',
        ble2_agent.start_acq,
        ble2_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
