#!/usr/bin/env python3
'''OCS agent for dS378 ethernet relay
'''
import time
import os
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.agent.dS378 import dS378

IP_DEFAULT = '192.168.215.241'
PORT_DEFAULT = 17123

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 100


class dS378Agent:
    '''OCS agent class for dS378 ethernet relay
    '''
    def __init__(self, agent, ip=IP_DEFAULT, port=17123):
        '''
        Parameters
        ----------
        ip : string
            IP address
        port : int
            Port number
        '''

        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self._dev = dS378(ip=ip, port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('relay',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params):
        '''Starts acquiring data.
        '''
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', 0.5)
        sleep_time = 1/f_sample - 0.1

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
                data = {'timestamp':current_time, 'block_name':'relay', 'data':{}}

                d_status = self._dev.get_status()
                relay_list = self._dev.get_relays()
                data['data']['V_sppl'] = d_status['V_sppl']
                data['data']['T_int'] = d_status['T_int']
                for i in range(8):
                    data['data'][f'Relay_{i+1}'] = relay_list[i]

                field_dict = {f'relay': {'V_sppl': d_status['V_sppl'],
                                         'T_int': d_status['T_int']}}
                session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('relay', data)
                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['relay'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    def set_relay(self, session, params=None):
        '''Turns the relay on/off or pulses it

        Parameters
        ----------
        relay_number : int
            relay_number, 1 -- 8
        on_off : int or RelayStatus
            1: on, 0: off
        pulse_time : int, 32 bit
            See document
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            if params.get('pulse_time') is None:
                params['pulse_time'] = 0

            self._dev.set_relay(relay_number=params['relay_number'],
                                on_off=params['on_off'],
                                pulse_time=params['pulse_time'])

        return True, f'Set values'

    def get_relays(self, session, params=None):
        ''' Get relay states'''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='get_relays') as acquired:
            if not acquired:
                self.log.warn('Could not start get_relays because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            d_status = self._dev.get_relays()
            session.data = {f'Relay_{i+1}': d_status[i] for i in range(8)}

        return True, f'Got relay status'


def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()

    args = parser.parse_args()
    site_config.reparse_args(args, 'dS378Agent')

    agent_inst, runner = ocs_agent.init_site_agent(args)

    kwargs = {}

    if args.port is not None:
        kwargs['port'] = args.port
    if args.ip is not None:
        kwargs['ip'] = args.ip

    ds_agent = dS378Agent(agent_inst, **kwargs)

    agent_inst.register_task(
        'set_relay',
        ds_agent.set_relay
    )

    agent_inst.register_task(
        'get_relays',
        ds_agent.get_relays
    )

    agent_inst.register_process(
        'acq',
        ds_agent.start_acq,
        ds_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
