#!/usr/bin/env python3
'''OCS agent for MAX31856 board in the stimulator box
'''
import time
import os
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.agent.max31856 import Max31856, CR0, SR

SPI_BUS_DEFAULT = [0, 0, 0, 0]
CS_LIST_DEFAULT = [1, 0, 2, 3]
MAX_PARAMETERS = ['nrf50', 'avgsel', 'tc_type']
LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10

class StmMaxAgent:
    '''OCS agent class for MAX31856 board
    '''
    def __init__(self, agent, spibus=None, cs_list=None):
        '''
        Parameters
        ----------
        spibus : list[int]
            SPI bus numbers
        cs_list : list[int]
            Chip select numbers
        '''
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        if spibus is None:
            spibus = SPI_BUS_DEFAULT

        if cs_list is None:
            cs_list = CS_LIST_DEFAULT

        self.devices = [Max31856(s, c) for s, c in zip(spibus, cs_list)]

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('tc_temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params):
        '''Starts acquiring data.
        '''
        f_sample = params.get('sampling_frequency', 2.5)
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
                data = {'timestamp':current_time, 'block_name':'temps', 'data':{}}

                for ch_num, dev in enumerate(self.devices):
                    temp = dev.get_temp()
                    cjtemp = dev.get_cjtemp(oneshot=False)
                    cr0 = dev._r(CR0)
                    sr = dev._r(SR)
                    data['data'][f'Channel_{ch_num}_T'] = temp
                    data['data'][f'Channel_{ch_num}_T_cj'] = cjtemp
                    data['data'][f'Channel_{ch_num}_CR0'] = cr0
                    data['data'][f'Channel_{ch_num}_SR'] = sr

                    field_dict = {f'Channel_{ch_num}': {'T': temp, 'T_cj': cjtemp, 'CR0': cr0, 'SR':sr}}
                    session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('tc_temperatures', data)
                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['tc_temperatures'].flush_buffer()

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
        '''A task to set sensor parameters for a MAX31856 device

        Parameters
        ----------
        channel : int
            Channel number to set.
        nrf50 : int
            50Hz/60Hz noise rejection filter.
                0: 60 Hz and harmonics
                1: 50 Hz and harmonics
        avgsel : int
            Averaging mode.
                0: 1 sample, 1: 2 samples, 2: 4 samples,
                3: 8 samples, 4+: 16 samples
        tc_type : int
            Themocouple type.
                0: B, 1: E, 2: J, 3: K, 4: N, 5: R, 6: S, 7: T
                8: Voltage mode, gain 8
                12: Voltage mode, gain 32
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='set_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            dev_inst = self.devices[params['channel']]

            conf = dev_inst.config

            for key, val in params.items():
                if key in MAX_PARAMETERS:
                    setattr(conf, key, val)

            dev_inst.config = conf

        return True, f'Set values for channel {params["channel"]}'

    def get_values(self, session, params=None):
        '''A task to provide configuration information'''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(3, job='get_values') as acquired:
            if not acquired:
                self.log.warn('Could not start set_values because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            dev_inst = self.devices[params['channel']]

            conf = dev_inst.config
            session.data = {'cmode': conf.cmode,
                            'ocfault': conf.ocfault,
                            'cj_disabled': conf.cj_disabled,
                            'fault': conf.fault,
                            'nrf50': conf.nrf50,
                            'avgsel': conf.avgsel,
                            'tc_type': conf.tc_type}


        return True, f'Got values for channel {params["channel"]}'



def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()
    _ = parser.add_argument_group('Agent Options')

    args = site_config.parse_args('StmMaxAgent')
    agent_inst, runner = ocs_agent.init_site_agent(args)

    stm_max_agent = StmMaxAgent(agent_inst)

    agent_inst.register_task(
        'set_values',
        stm_max_agent.set_values
    )

    agent_inst.register_task(
        'get_values',
        stm_max_agent.get_values
    )

    agent_inst.register_process(
        'acq',
        stm_max_agent.start_acq,
        stm_max_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)

if __name__ == '__main__':
    main()
