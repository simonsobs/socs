"""Michael Randall
mrandall@ucsd.edu"""

import argparse
import socket
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.tektronix3021c.drivers import TektronixInterface


class TektronixAWGAgent:
    """Tektronix3021c Function Generator Agent.

    Args:
        ip_address (string): The IP address of the gpib to ethernet
            controller connected to the function generator.
        gpib_slot (int): The gpib address currently set
            on the function generator.

    """

    def __init__(self, agent, ip_address, gpib_slot):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None

        self.ip_address = ip_address
        self.gpib_slot = gpib_slot
        self.monitor = False

        self.awg = None
        # Registers data feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('awg',
                                 record=True,
                                 agg_params=agg_params)

    @ocs_agent.param('_')
    def init(self, session, params=None):
        """init()

        **Task** - Initialize connection to Tektronix AWG.

        """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.awg = TektronixInterface(self.ip_address, self.gpib_slot)
                self.idn = self.awg.identify()

            except socket.timeout as e:
                self.log.error("""Tektronix AWG
                               timed out during connect -> {}""".format(e))
                return False, "Timeout"

            self.log.info("Connected to AWG: {}".format(self.idn))

        return True, 'Initialized AWG.'

    @ocs_agent.param('frequency', type=float, check=lambda x: 0 <= x <= 25e6)
    def set_frequency(self, session, params=None):
        """set_frequency(frequency)

        **Task** - Set frequency of the function generator.

        Parameters:
            frequency (float): Frequency to set in Hz. Must be between 0 and
                25,000,000.
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                freq = params['frequency']

                self.awg.set_freq(freq)

                data = {'timestamp': time.time(),
                        'block_name': "AWG_frequency_cmd",
                        'data': {'AWG_frequency_cmd': freq}
                        }
                self.agent.publish_to_feed('awg', data)
            else:
                return False, "Could not acquire lock"

        return True, 'Set frequency {} Hz'.format(freq)

    @ocs_agent.param('amplitude', type=float, check=lambda x: 0 <= x <= 10)
    def set_amplitude(self, session, params=None):
        """set_amplitude(amplitude)

        **Task** - Set peak to peak voltage of the function generator.

        Parameters:
            amplitude (float): Peak to Peak voltage to set. Must be between 0
                and 10.

        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                amp = params['amplitude']

                self.awg.set_amp(amp)

                data = {'timestamp': time.time(),
                        'block_name': "AWG_amplitude_cmd",
                        'data': {'AWG_amplitude_cmd': amp}
                        }
                self.agent.publish_to_feed('awg', data)
            else:
                return False, "Could not acquire lock"

        return True, 'Set amplitude to {} Vpp'.format(params)

    @ocs_agent.param('state', type=bool)
    def set_output(self, session, params=None):
        """set_output(state)

        **Task** - Turn function generator output on or off.

        Parameters:
            state (bool): True for on, False for off.

        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                state = params.get("state")

                self.awg.set_output(state)

                data = {'timestamp': time.time(),
                        'block_name': "AWG_output_cmd",
                        'data': {'AWG_output_cmd': int(state)}
                        }
                self.agent.publish_to_feed('awg', data)

            else:
                return False, "Could not acquire lock"

        return True, 'Set Output to {}.'.format(params)


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address', type=str,
                        help="IP address of Tektronix device.")
    pgroup.add_argument('--gpib-slot', type=int,
                        help="GPIB slot of Tektronix device.")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class="Tektronix AWG",
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    p = TektronixAWGAgent(agent, args.ip_address, args.gpib_slot)

    agent.register_task('init', p.init, startup=True)
    agent.register_task('set_frequency', p.set_frequency)
    agent.register_task('set_amplitude', p.set_amplitude)
    agent.register_task('set_output', p.set_output)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
