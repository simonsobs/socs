"""Michael Randall
mrandall@ucsd.edu"""

import time
import os
import socket
import argparse

from socs.agent.tektronix3021c_driver import tektronixInterface

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class TektronixAWGAgent:
    """Tektronix3021c Agent.

    Args:
        ip_address (string): the IP address of the gpib to ethernet
            controller connected to the function generator.

        gpib_slot (int): the gpib address currently set
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

    def init_awg(self, session, params=None):
        """ Task to connect to Tektronix AWG """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.awg = tektronixInterface(self.ip_address, self.gpib_slot)
                self.idn = self.awg.identify()

            except socket.timeout as e:
                self.log.error("""Tektronix AWG
                               timed out during connect -> {}""".format(e))
                return False, "Timeout"

            self.log.info("Connected to AWG: {}".format(self.idn))

        return True, 'Initialized AWG.'

    def set_frequency(self, session, params=None):
        """
        Sets frequency of function generator:

        Args:
            frequency (float): Frequency to set in Hz.
            Must be between 0 and 25,000,000.
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                freq = params.get("frequency")

                try:
                    float(freq)

                except ValueError as e:
                    return False, """Frequency must
                                    be a float or int -> {}""".format(e)

                except TypeError as e:
                    return False, """Frequency must
                                    not be of NoneType -> {}""".format(e)

                if 0 < freq < 25E6:
                    self.awg.setFreq(freq)

                    data = {'timestamp': time.time(),
                            'block_name': "AWG_frequency",
                            'data': {'AWG_frequency': freq}
                            }
                    self.agent.publish_to_feed('awg', data)

                else:
                    return False, """Invalid input:
                        Frequency must be between 0 and 25,000,000 Hz"""

            else:
                return False, "Could not acquire lock"

        return True, 'Set frequency {} Hz'.format(params)

    def set_amplitude(self, session, params=None):
        """
        Sets current of power supply:

        Args:
            amplitude (float): Peak to Peak voltage to set.
            Must be between 0 and 10.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                amp = params.get('amplitude')
                try:
                    float(amp)

                except ValueError as e:
                    return False, """Amplitude must be
                                    a float or int -> {}""".format(e)

                except TypeError as e:
                    return False, """Amplitude must not be
                                    of NoneType -> {}""".format(e)

                if 0 < amp < 10:
                    self.awg.setAmp(amp)

                    data = {'timestamp': time.time(),
                            'block_name': "AWG_amplitude",
                            'data': {'AWG_amplitude': amp}
                            }
                    self.agent.publish_to_feed('awg', data)

                else:
                    return False, """Amplitude must be
                                    between 0 and 10 Volts peak to peak"""

            else:
                return False, "Could not acquire lock"

        return True, 'Set amplitude to {} Vpp'.format(params)

    def set_output(self, session, params=None):
        """
        Task to turn channel on or off.

        Args:
            state (bool): True for on, False for off.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                state = params.get("state")

                try:
                    bool(state)

                except ValueError as e:
                    return False, "State must be a boolean -> {}".format(e)

                except TypeError as e:
                    return False, """State must not
                                    be of NoneType -> {}""".format(e)

                self.awg.setOutput(state)

                data = {'timestamp': time.time(),
                        'block_name': "AWG_output",
                        'data': {'AWG_output': int(state)}
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
                        help="IP address of tektronix device")
    pgroup.add_argument('--gpib-slot', type=int,
                        help="GPIB slot of tektronix device")
    return parser


if __name__ == '__main__':

    parser = make_parser()
    args = site_config.parse_args(agent_class="Tektronix AWG", parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    p = TektronixAWGAgent(agent, args.ip_address, args.gpib_slot)

    agent.register_task('init', p.init_awg, startup=True)
    agent.register_task('set_frequency', p.set_frequency)
    agent.register_task('set_amplitude', p.set_amplitude)
    agent.register_task('set_output', p.set_output)

    runner.run(agent, auto_reconnect=True)
