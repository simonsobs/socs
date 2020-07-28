
"""Michael Randall
	mrandall@ucsd.edu"""

import time
import os
import socket

from agilentrf_driver import agilentRFInterface

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class AgilentRFAgent:
    def __init__(self, agent, ip_address, gpib_slot):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.gpib_slot = gpib_slot
        self.monitor = False

        self.rf = None
        
        # Registers data feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('AgilentRF',
                                 record=True,
                                 agg_params=agg_params)


    def init_awg(self, session, params=None):
        """ Task to connect to Agilent RF source """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.rf = agilentRFInterface(self.ip_address, self.gpib_slot)
                self.idn = self.rf.identify()
            except socket.timeout as e:
                self.log.error("Agilent RF source timed out during connect")
                return False, "Timeout"
            self.log.info("Connected to RF source: {}".format(self.idn))

        return True, 'Initialized RF source.'


    def set_cwFrequency(self, session, params=None):
        """
        Sets frequency of RF source:

        Args:
            frequency (float): Frequency to set. 
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                freq = params['frequency']
                self.rf.set_cwFrequency(freq)
                
                data = {'timestamp': time.time(),
                       'block_name': "cwFrequency",
                        'data': {'cwFrequency': freq}
                       }
                self.agent.publish_to_feed('AgilentRF', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Set cwFrequency {}'.format(params)

    def set_power(self, session, params=None):
        """
        Sets the power of the RF source in dBm:

        Args:
            Amplitude (float): Peak to Peak voltage to set. Must be between 0 and 10.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                power = params['power']
                self.rf.set_power(power)
                
                data = {'timestamp': time.time(),
                       'block_name': "outputPower",
                        'data': {'outputPower': power}
                       }
                self.agent.publish_to_feed('AgilentRF', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Set output power to {} '.format(params)

    def set_output(self, session, params=None):
        """
        Task to turn rf source on or off.

        Args:
            state (bool): True for on, False for off.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                state = params['state']
                self.rf.set_output(state)
                
                data = {'timestamp': time.time(),
                       'block_name': "outputState",
                        'data': {'outputState': int(state)}
                       }
                self.agent.publish_to_feed('AgilentRF', data)
                
            else:
                return False, "Could not acquire lock"

        return True, 'Initialized AgilentRF.'

if __name__ == '__main__':
    parser = site_config.add_arguments()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--gpib-slot')

    # Parse comand line.
    args = parser.parse_args()
    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Agilent RF source')

    agent, runner = ocs_agent.init_site_agent(args)

    p = AgilentRFAgent(agent, args.ip_address, int(args.gpib_slot))

    agent.register_task('init', p.init_awg)
    agent.register_task('set_cwFrequency', p.set_cwFrequency)
    agent.register_task('set_power', p.set_power)
    agent.register_task('set_output', p.set_output)

    runner.run(agent, auto_reconnect=True)

