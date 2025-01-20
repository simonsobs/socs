#!/usr/bin/env python3
'''OCS agent for dS378 ethernet relay
'''
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.devantech_dS378.drivers import DS378

PORT_DEFAULT = 17123

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10
ACQ_TIMEOUT = 100


class DS378Agent:
    """OCS agent class for dS378 ethernet relay

    Parameters
    ----------
    ip : string
        IP address
    port : int
        Port number
    """

    def __init__(self, agent, ip, port=PORT_DEFAULT):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self._dev = DS378(ip=ip, port=port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('relay',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('sampling_frequency', default=0.5, type=float)
    def acq(self, session, params):
        """acq()

        **Process** - Monitor status of the relay.

        Parameters
        ----------
        sampling_frequency : float, optional
            Sampling frequency in Hz, defaults to 0.5 Hz.

        Notes
        -----
        An example of the session data::

            >>> response.session['data']

            {'V_sppl': 11.8,
             'T_int': 30.8,
             'Relay_1': 0,
             'Relay_2': ...,
             'timestamp': 1736541796.779634
            }
        """
        f_sample = params.get('sampling_frequency', 0.5)
        pace_maker = Pacemaker(f_sample)

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
                data = {'timestamp': current_time, 'block_name': 'relay', 'data': {}}

                try:
                    d_status = self._dev.get_status()
                    relay_list = self._dev.get_relays()
                    if session.degraded:
                        self.log.info('Connection re-established.')
                        session.degraded = False
                except ConnectionError:
                    self.log.error('Failed to get data from relay. Check network connection.')
                    session.degraded = True
                    time.sleep(1)
                    continue

                data['data']['V_sppl'] = d_status['V_sppl']
                data['data']['T_int'] = d_status['T_int']
                for i in range(8):
                    data['data'][f'Relay_{i + 1}'] = relay_list[i]

                field_dict = {'V_sppl': d_status['V_sppl'],
                              'T_int': d_status['T_int']}

                for i in range(8):
                    field_dict[f'Relay_{i + 1}'] = relay_list[i]

                session.data.update(field_dict)

                self.agent.publish_to_feed('relay', data)
                session.data.update({'timestamp': current_time})

                pace_maker.sleep()

            self.agent.feeds['relay'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'

    @ocs_agent.param('relay_number', type=int, check=lambda x: 1 <= x <= 8)
    @ocs_agent.param('on_off', type=int, choices=[0, 1])
    @ocs_agent.param('pulse_time', default=None, type=int, check=lambda x: 0 <= x <= 2**32 - 1)
    def set_relay(self, session, params=None):
        """set_relay(relay_number, on_off, pulse_time=None)

        **Task** - Turns the relay on/off or pulses it.

        Parameters
        ----------
        relay_number : int
            Relay number to manipulate. Values must be in range [1, 8].
        on_off : int
            1 (0) to turn on (off).
        pulse_time : int, optional
            Pulse time in ms. Values must be in range [0, 4294967295].

        Notes
        -----
        This command pulses relay for a given period when ``pulse_time``
        argument is specified, otherwise just turns a relay on or off.

        """
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

        return True, 'Set values'

    def get_relays(self, session, params=None):
        """get_relays()

        **Task** - Returns current relay status.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'Relay_1': 1,
             'Relay_2': ...,
             'timestamp': 1736541796.779634
            }
        """
        with self.lock.acquire_timeout(3, job='get_relays') as acquired:
            if not acquired:
                self.log.warn('Could not start get_relays because '
                              f'{self.lock.job} is already running')
                return False, 'Could not acquire lock.'

            d_status = self._dev.get_relays()
            session.data = {f'Relay_{i + 1}': d_status[i] for i in range(8)}
            session.data.update({'timestamp': time.time()})

        return True, 'Got relay status'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--port', default=PORT_DEFAULT, type=int,
                        help='Port number for TCP communication.')
    pgroup.add_argument('--ip_address',
                        help='IP address of the device.')

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = make_parser()
    args = site_config.parse_args(agent_class='DS378Agent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)
    ds_agent = DS378Agent(agent_inst, ip=args.ip_address, port=args.port)

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
        ds_agent.acq,
        ds_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
