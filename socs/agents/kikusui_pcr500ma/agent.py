#!/usr/bin/env python3
'''OCS agent for dS378 ethernet relay
'''
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.kikusui_pcr500ma.drivers import PCR500MA, TIMEOUT_DEFAULT

IP_DEFAULT = '192.168.215.80'
PORT_DEFAULT = 5025

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 20


class PCRAgent:
    '''OCS agent class for PCR500MA current source
    '''

    def __init__(self, agent, ip_addr=IP_DEFAULT, port=PORT_DEFAULT, timeout=TIMEOUT_DEFAULT):
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

        self._dev = PCR500MA(ip_addr=ip_addr, port=port, timeout=timeout)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('heater_source',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params):
        '''Starts acquiring data.
        '''
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', 0.2)
        sleep_time = 1 / f_sample - 0.1

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            session.set_status('running')

            self.take_data = True
            session.data = {'fields': {}}
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
                data = {'timestamp': current_time, 'block_name': 'heater_source', 'data': {}}

                i_ac = self._dev.meas_current_ac()
                v_ac = self._dev.meas_volt_ac()
                p_ac = self._dev.meas_power_ac()
                sw_status = self._dev.get_output()
                data['data']['I_AC'] = i_ac
                data['data']['V_AC'] = v_ac
                data['data']['P_AC'] = p_ac
                data['data']['output'] = 1 if sw_status else 0

                field_dict = {'heater_source': {'I_AC': i_ac,
                                                'V_AC': v_ac,
                                                'P_AC': p_ac,
                                                'output': 1 if sw_status else 0}}
                session.data['fields'].update(field_dict)

                self.agent.publish_to_feed('heater_source', data)
                session.data.update({'timestamp': current_time})

                time.sleep(sleep_time)

            self.agent.feeds['heater_source'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    def set_output(self, session, params=None):
        '''Turns the the source on/off

        Parameters
        ----------
        output : bool
            True : output on
            False : output off
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_output') as acquired:
            if not acquired:
                self.log.warn('Could not start set_output because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            output_on = params['output']
            force = params.get('force', False)
            # Use measurement value when checking turning off threshold.
            use_meas_val = params.get('use_meas_val', not output_on)

            if force:
                self._dev.set_output(output=output_on)
            else:
                if use_meas_val:
                    volt_ac = self._dev.meas_volt_ac()
                    if volt_ac >= 0.2:
                        return False, 'Voltage too high to turn on/off.'
                else:
                    volt_set = self._dev.get_volt_ac()
                    if volt_set != 0:
                        return False, 'Voltage too high to turn on/off.'

                self._dev.set_output(output=output_on)

        return True, f'Set output for PCR: {params["output"]}'

    def get_output(self, session, params=None):
        ''' Get output status

        Returns
        -------
        output : bool
            True : output on
            False : output off
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='get_output') as acquired:
            if not acquired:
                self.log.warn('Could not start get_output because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            d_status = self._dev.get_output()
            session.data = {'output': d_status}

        return True, f'Got output status of PCR: {d_status}'

    def set_volt_ac(self, session, params=None):
        '''Set AC voltage

        Parameters
        ----------
        volt_set : float
            AC voltage setting in V
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_volt_ac') as acquired:
            if not acquired:
                self.log.warn('Could not start set_volt_ac because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self._dev.set_volt_ac(volt=params['volt_set'])

        return True, f'Set voltage for PCR: {params["volt_set"]}'

    def get_volt_ac(self, session, params=None):
        ''' Get AC voltage setting

        Returns
        -------
        volt_set : float
            AC voltage setting in V
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='get_volt_ac') as acquired:
            if not acquired:
                self.log.warn('Could not start get_volt_ac because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            volt_set = self._dev.get_volt_ac()
            session.data = {'volt_set': volt_set}

        return True, f'Got AC voltage setting: {volt_set}'

    def meas(self, session, params=None):
        ''' Perform measuremnets

        Returns
        -------
        i_ac : float
            Measured AC current in A.
        v_ac : float
            Measured AC voltage in V.
        p_ac : float
            Measured AC power in W.
        f_ac : float
            Measured AC frequency in Hz.
        '''
        if params is None:
            params = {}

        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='meas') as acquired:
            if not acquired:
                self.log.warn('Could not start meas because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            i_ac = self._dev.meas_current_ac()
            v_ac = self._dev.meas_volt_ac()
            p_ac = self._dev.meas_power_ac()
            f_ac = self._dev.meas_freq()
            session.data = {'i_ac': i_ac,
                            'v_ac': v_ac,
                            'p_ac': p_ac,
                            'f_ac': f_ac}

        return True, f'Measured AC parameters: {v_ac}'


def main():
    '''Boot OCS agent'''
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()

    args = parser.parse_args()
    site_config.reparse_args(args, 'PCRAgent')

    agent_inst, runner = ocs_agent.init_site_agent(args)

    kwargs = {}

    if args.port is not None:
        kwargs['port'] = args.port
    if args.ip is not None:
        kwargs['ip_addr'] = args.ip

    pcr_agent = PCRAgent(agent_inst, **kwargs)

    agent_inst.register_task(
        'set_output',
        pcr_agent.set_output
    )

    agent_inst.register_task(
        'get_output',
        pcr_agent.get_output
    )

    agent_inst.register_task(
        'set_volt_ac',
        pcr_agent.set_volt_ac
    )

    agent_inst.register_task(
        'get_volt_ac',
        pcr_agent.get_volt_ac
    )

    agent_inst.register_task(
        'meas',
        pcr_agent.meas
    )

    agent_inst.register_process(
        'acq',
        pcr_agent.start_acq,
        pcr_agent.stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
