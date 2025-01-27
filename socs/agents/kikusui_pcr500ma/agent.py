#!/usr/bin/env python3
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.kikusui_pcr500ma.drivers import PCR500MA, VOLT_ULIM_SOFT

PORT_DEFAULT = 5025

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 5


class PCR500MAAgent:
    """OCS agent class for PCR500MA current source

    Parameters
    ----------
    ip : string
        IP address
    port : int
        Port number
    """

    def __init__(self, agent, ip_addr, port=PORT_DEFAULT):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self._dev = PCR500MA(ip_addr=ip_addr, port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('heater_source',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('sampling_frequency', default=0.2, type=float)
    def acq(self, session, params):
        """acq(sampling_frequency=0.2)

        **Process** - Monitor status of the relay.

        Parameters
        ----------
        sampling_frequency : float, optional
            Sampling frequency in Hz, defaults to 0.2 Hz.

        Notes
        -----
        An example of the session data::

            >>> response.session['data']
            {"I_AC": 0.00475843,
             "V_AC": 0.0371215,
             "P_AC": 0.0,
             "f_AC": 60.0,
             "output": 0,
             "timestamp": 1737367649.2595236
            }
        """
        f_sample = params.get('sampling_frequency')
        pace_maker = Pacemaker(f_sample)

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    f'Could not start acq because {self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self.take_data = True
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

                try:
                    i_ac = self._dev.meas_current_ac()
                    v_ac = self._dev.meas_volt_ac()
                    p_ac = self._dev.meas_power_ac()
                    f_ac = self._dev.meas_freq()
                    sw_status = self._dev.get_output()
                    if session.degraded:
                        self.log.info('Connection re-established.')
                        session.degraded = False
                except ConnectionError:
                    self.log.error('Failed to get data from Kikusui PCR. Check network connection.')
                    session.degraded = True
                    time.sleep(1)
                    continue

                data['data']['I_AC'] = i_ac
                data['data']['V_AC'] = v_ac
                data['data']['P_AC'] = p_ac
                data['data']['f_AC'] = f_ac
                data['data']['output'] = 1 if sw_status else 0

                field_dict = {'I_AC': i_ac,
                              'V_AC': v_ac,
                              'P_AC': p_ac,
                              'f_AC': f_ac,
                              'output': 1 if sw_status else 0}

                session.data.update(field_dict)

                self.agent.publish_to_feed('heater_source', data)
                session.data.update({'timestamp': current_time})

                pace_maker.sleep()

            self.agent.feeds['heater_source'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    @ocs_agent.param('output', type=bool)
    @ocs_agent.param('force', default=False, type=bool)
    def set_output(self, session, params=None):
        """set_output(output, force=False)

        **Task** - Turns the output on or off.

        Parameters
        ----------
        output : bool
            True : output on
            False : output off

        force : bool, default False
            Force output on / off without checking output value.

        Notes
        -----
        This function measures the output voltage when turning off
        and checks the voltage setting when turning on by default. If the
        voltage is too high it will not change state to avoid an abrupt
        change in applied voltage.
        Set `force` option to `True` when this behavior is unwanted.
        """
        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_output') as acquired:
            if not acquired:
                self.log.warn('Could not start set_output because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            output_on = params['output']
            force = params['force']
            # Use measurement value when checking turning off threshold.
            use_meas_val = not output_on

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

    @ocs_agent.param('_')
    def get_output(self, session, params=None):
        """get_output()

        **Task** - Get output status.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'output': True,
             'timestamp': 1737367649.2595236
            }
        """
        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='get_output') as acquired:
            if not acquired:
                self.log.warn('Could not start get_output because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            d_status = self._dev.get_output()
            session.data = {'output': d_status,
                            'timestamp': time.time()}

        return True, f'Got output status of PCR: {d_status}'

    @ocs_agent.param('volt_set', type=float, check=lambda x: 0 <= x <= VOLT_ULIM_SOFT)
    def set_volt_ac(self, session, params=None):
        """set_volt_ac(volt_set)

        **Task** - Set AC voltage value.

        Parameters
        ----------
        volt_set : float
            AC voltage setting in V. Values must be in range [0, 51].
        """
        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='set_volt_ac') as acquired:
            if not acquired:
                self.log.warn('Could not start set_volt_ac because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            self._dev.set_volt_ac(volt=params['volt_set'])

        return True, f'Set voltage for PCR: {params["volt_set"]}'

    @ocs_agent.param('_')
    def get_volt_ac(self, session, params=None):
        """get_volt_ac()

        **Task** - Get AC voltage setting.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'volt_set': 10.0,
             'timestamp': 1737367649.2595236
            }
        """
        with self.lock.acquire_timeout(ACQ_TIMEOUT, job='get_volt_ac') as acquired:
            if not acquired:
                self.log.warn('Could not start get_volt_ac because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            volt_set = self._dev.get_volt_ac()
            session.data = {'volt_set': volt_set,
                            'timestamp': time.time()}

        return True, f'Got AC voltage setting: {volt_set}'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=PORT_DEFAULT, type=int,
                        help='Port number for TCP communication.')
    pgroup.add_argument('--ip-address',
                        help='IP address of the device.')

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = site_config.add_arguments()

    parser = make_parser()
    args = site_config.parse_args(agent_class='PCR500MAAgent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)

    pcr_agent = PCR500MAAgent(agent_inst, ip_addr=args.ip_address, port=args.port)

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

    agent_inst.register_process(
        'acq',
        pcr_agent.acq,
        pcr_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
