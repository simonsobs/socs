"""Michael Randall
	mrandall@ucsd.edu"""

import time
import os
import socket

from tektronix_driver import tektronixInterface

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class TektronixAWGAgent:
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
        self.agent.register_feed('AWG',
                                 record=True,
                                 agg_params=agg_params)


    def init_awg(self, session, params=None):
        """ Task to connect to Tektronix AWG """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.awg = tektronixInterface(self.ip_address, self.gpib_slot)
                self.idn = self.awg.identify()
            except socket.timeout as e:
                self.log.error("Tektronix AWG timed out during connect")
                return False, "Timeout"
            self.log.info("Connected to AWG: {}".format(self.idn))

        return True, 'Initialized AWG.'


    def set_frequency(self, session, params=None):
        """
        Sets frequency of function generator:

        Args:
            frequency (float): Frequency to set. Must be between 0 and 25,000,000
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                freq = params['frequency']
                self.awg.setFreq(freq)
                
                data = {'timestamp': time.time(),
                       'block_name': "AWG_frequency",
                        'data': {'AWG_frequency': freq}
                       }
                self.agent.publish_to_feed('AWG', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Set frequency {}'.format(params)

    def set_amplitude(self, session, params=None):
        """
        Sets current of power supply:

        Args:
            Amplitude (float): Peak to Peak voltage to set. Must be between 0 and 10.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                amp = params['amplitude']
                self.awg.setAmp(amp)
                
                data = {'timestamp': time.time(),
                       'block_name': "AWG_amplitude",
                        'data': {'AWG_amplitude': amp}
                       }
                self.agent.publish_to_feed('AWG', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Set amplitude to {} '.format(params)

    def set_output(self, session, params=None):
        """
        Task to turn channel on or off.

        Args:
            state (bool): True for on, False for off.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                state = params['state']
                self.awg.setOutput(state)
                
                data = {'timestamp': time.time(),
                       'block_name': "AWG_output",
                        'data': {'AWG_output': int(state)}
                       }
                self.agent.publish_to_feed('AWG', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Initialized AWG.'

if __name__ == '__main__':
    parser = site_config.add_arguments()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--gpib-slot')

    # Parse comand line.
    args = parser.parse_args()
    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Tektronix AWG')

    agent, runner = ocs_agent.init_site_agent(args)

    p = TektronixAWGAgent(agent, args.ip_address, int(args.gpib_slot))

    agent.register_task('init', p.init_awg)
    agent.register_task('set_frequency', p.set_frequency)
    agent.register_task('set_amplitude', p.set_amplitude)
    agent.register_task('set_output', p.set_output)

    runner.run(agent, auto_reconnect=True)
