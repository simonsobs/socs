#!/usr/bin/env python3
"""OCS agent for thermometer board in the stimulator box
"""
import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.stimulator_thermometer.drivers import (Max31856,
                                                        from_spi_node_path)

LOCK_RELEASE_SEC = 1.
LOCK_RELEASE_TIMEOUT = 10


class StimThermometerAgent:
    """OCS agent class for stimulator thermometer.

    Parameters
    ----------
    paths_spinode : list of str or pathlib.Path
        List of path to SPI nodes of temperature devices.
    """

    def __init__(self, agent, paths_spinode):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.take_data = False

        self.devices = [from_spi_node_path(path) for path in paths_spinode]

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('sampling_frequency', type=float, default=1)
    def acq(self, session, params):
        """acq()

        **Process** - Fetch temperatures from the thermometer readers.

        Parameters
        ----------
        sampling_frequency : float, optional
            Sampling frequency in Hz, default to 1 Hz.

        Notes
        -----
        An example of the session data::

            >>> response.session['data']

            {"Channel_0": {"T":15.092116135817285},
             "Channel_1": {"T":15.092116135817285},
             "Channel_2": {"T":15.40625,"T_cj":16.796875},
             "Channel_3": {"T":15.4921875,"T_cj":16.453125}},
             ...
             "timestamp": 1738827824.2523127
            }
        """
        f_sample = params['sampling_frequency']
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
                if time.time() - last_release > LOCK_RELEASE_SEC:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=LOCK_RELEASE_TIMEOUT):
                        print(f'Re-acquire failed: {self.lock.job}')
                        return False, 'Could not re-acquire lock.'

                current_time = time.time()

                for ch_num, dev in enumerate(self.devices):
                    data = {'timestamp': current_time, 'block_name': f'temp_{ch_num}', 'data': {}}
                    chan_string = f'Channel_{ch_num}'

                    temp = dev.get_temp()
                    data['data'][chan_string + '_T'] = temp
                    self.agent.publish_to_feed('temperatures', data)

                    if isinstance(dev, Max31856):
                        cjtemp = dev.get_temp_ambient()
                        data['data'][chan_string + '_T_cj'] = cjtemp
                        field_dict = {chan_string: {'T': temp, 'T_cj': cjtemp}}
                    else:
                        field_dict = {chan_string: {'T': temp}}

                    session.data.update(field_dict)

                session.data.update({'timestamp': current_time})
                pace_maker.sleep()

            self.agent.feeds['temperatures'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'

        return False, 'acq is not currently running.'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--paths-spinode', nargs='*', type=str, required=True,
                        help="Path to the spi nodes.")

    return parser


def main(args=None):
    """Boot OCS agent"""
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    parser = make_parser()
    args = site_config.parse_args('StimThermometerAgent',
                                  parser=parser,
                                  args=args)

    agent_inst, runner = ocs_agent.init_site_agent(args)
    stim_max_agent = StimThermometerAgent(agent_inst, args.paths_spinode)

    agent_inst.register_process(
        'acq',
        stim_max_agent.acq,
        stim_max_agent._stop_acq,
        startup=True
    )

    runner.run(agent_inst, auto_reconnect=True)


if __name__ == '__main__':
    main()
