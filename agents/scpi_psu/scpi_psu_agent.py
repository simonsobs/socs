import time
import os
import socket
import argparse
from socs.agent.scpi_psu_driver import PsuPrologixInterface
from socs.agent.scpi_psu_driver import PsuEthernetInterface

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock


class ScpiPsuAgent:
    def __init__(self, agent, ip_address, gpib_slot, port_number, interface_type):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.gpib_slot = gpib_slot
        self.port_number = port_number
        self.interface_type = interface_type
        self.monitor = False

        self.psu = None
        self.idn = None

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 10 * 60,
        }
        self.agent.register_feed('psu_output',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    def init_psu(self, session, params=None):
        """
            Task to connect to power supply.
            Requires interface_type to be defined: 'gpib' or 'ethernet'.
            Incorrectly defining interface_type will cause the socket to not initialize.
        """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                if self.interface_type == 'gpib':
                    self.psu = PsuPrologixInterface(self.ip_address, self.gpib_slot)

                elif self.interface_type == 'ethernet':
                    self.psu = PsuEthernetInterface(self.ip_address, self.port_number)

                self.idn = self.psu.identify()

            except AttributeError as e:
                self.log.error(f"Socket not initialized. Check interface type in config: {e}")
                return False, "Socket not initialized"

            except socket.timeout as e:
                self.log.error(f"PSU timed out during connect: {e}")
                return False, "Timeout"

            self.log.info("Connected to psu: {}".format(self.idn))

        return True, 'Initialized PSU.'

    def monitor_output(self, session, params=None):
        """
            Process to continuously monitor PSU output current and voltage and
            send info to aggregator.

            Args:
                wait (float, optional):
                    time to wait between measurements [seconds].
                channels (list[int], optional):
                    channels to monitor. [1, 2, 3] by default.
        """
        if params is None:
            params = {}

        wait_time = params.get('wait', 1)
        channels = params.get('channels', [1, 2, 3])
        test_mode = params.get('test_mode', False)

        session.set_status('running')
        self.monitor = True

        while self.monitor:
            with self.lock.acquire_timeout(1) as acquired:
                if acquired:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'output',
                        'data': {}
                    }

                    for chan in channels:
                        data['data']["Voltage_{}".format(chan)] = self.psu.get_volt(chan)
                        data['data']["Current_{}".format(chan)] = self.psu.get_curr(chan)

                    # self.log.info(str(data))
                    # print(data)
                    self.agent.publish_to_feed('psu_output', data)

                    # Allow this process to be queried to return current data
                    session.data = data

                else:
                    self.log.warn("Could not acquire in monitor_current")

            time.sleep(wait_time)

            if test_mode:
                break

        return True, "Finished monitoring current"

    def stop_monitoring(self, session, params=None):
        self.monitor = False
        return True, "Stopping current monitor"

    def set_voltage(self, session, params=None):
        """
        Sets voltage of power supply:

        Args:
            channel (int): Channel number (1, 2, or 3)
            volts (float): Voltage to set. Must be between 0 and 30.
        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_volt(params['channel'], params['volts'])
            else:
                return False, "Could not acquire lock"

        return True, 'Set channel {} voltage to {}'.format(params['channel'], params['volts'])

    def set_current(self, session, params=None):
        """
        Sets current of power supply:

        Args:
            channel (int): Channel number (1, 2, or 3)
            "current" (float): Curent to set. Must be between x and y.
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_curr(params['channel'], params['current'])
            else:
                return False, "Could not acquire lock"

        return True, 'Set channel {} current to {}'.format(params['channel'], params['current'])

    def set_output(self, session, params=None):
        """
        Task to turn channel on or off.

        Args:
            channel (int): Channel number (1, 2, or 3)
            state (bool): True for on, False for off
        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.psu.set_output(params['channel'], params['state'])
            else:
                return False, "Could not acquire lock"

        return True, 'Initialized PSU.'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--gpib-slot')
    pgroup.add_argument('--port-number')
    pgroup.add_argument('--interface-type')

    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='ScpiPsuAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    p = ScpiPsuAgent(agent, args.ip_address, int(args.gpib_slot),
                    int(args.port_number), args.interface_type)

    agent.register_task('init', p.init_psu)
    agent.register_task('set_voltage', p.set_voltage)
    agent.register_task('set_current', p.set_current)
    agent.register_task('set_output', p.set_output)

    agent.register_process('monitor_output', p.monitor_output, p.stop_monitoring)

    runner.run(agent, auto_reconnect=True)
