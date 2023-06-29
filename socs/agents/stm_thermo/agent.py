#!/usr/bin/env python3
'''OCS agent for MAX31856 board in the stimulator box
'''
import time
import os
import txaio
import argparse
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from socs.agents.stm_thermo.drivers import from_spi_node_path, Max31856

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10

class StmThermometerAgent:
    '''OCS agent class for stimulator thermometer.
    '''
    def __init__(self, agent, devices):
        '''
        Parameters
        ----------
        devices : list of str or pathlib.Path
            List of path to SPI nodes of temperature devices.
        '''
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self.devices = devices

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def acq(self, session, params):
        f_sample = params.get('sampling_frequency', 1)
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
                if time.time() - last_release > LOCK_RELEASE_SEC:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=LOCK_RELEASE_TIMEOUT):
                        print(f'Re-acquire failed: {self.lock.job}')
                        return False, 'Could not re-acquire lock.'

                current_time = time.time()
                data = {'timestamp':current_time, 'block_name':'temps', 'data':{}}

                for ch_num, dev in enumerate(self.devices):
                    chan_string = f'Channel_{ch_num}'

                    temp = dev.get_temp()
                    data['data'][chan_string + '_T'] = temp

                    if isinstance(dev, Max31856):
                        cjtemp = dev.get_temp_ambient()
                        data['data'][chan_string + '_T_cj'] = cjtemp
                        field_dict = {chan_string: {'T': temp, 'T_cj': cjtemp}}
                    else:
                        field_dict = {chan_string: {'T': temp}}

                    session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('temperatures', data)

                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['temperatures'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    # parser = site_config.add_arguments()
    parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--paths_spinode', nargs='*', type=str, required=True,
                        help="Path to the spi nodes.")

    args = site_config.parse_args('StmThermometerAgent', parser=parser)
    agent_inst, runner = ocs_agent.init_site_agent(args)

    devices = [from_spi_node_path(path) for path in args.paths_spinode]

    stm_max_agent = StmThermometerAgent(agent_inst, devices)

    agent_inst.register_process(
        'acq',
        stm_max_agent.acq,
        stm_max_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)

if __name__ == '__main__':
    main()
