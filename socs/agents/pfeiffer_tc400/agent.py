import argparse
import socket
import time
from os import environ

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.pfeiffer_tc400.drivers import PfeifferTC400


class PfeifferTC400Agent:
    """Agent to connect to a pfeiffer tc400 electronic drive unit controlling a
    turbo pump via a serial-to-ethernet converter.

    Parameters
    ----------
    ip_address : str
        IP address for the serial-to-ethernet converter
    port_number : int
        Serial-to-ethernet converter port
    turbo_address : int
        An internal address used to communicate between the power supplies and
        the tc400. Found on the front screen of the power supplies.
    """

    def __init__(self, agent, ip_address, port_number, turbo_address):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.port_number = port_number
        self.turbo_address = turbo_address
        self.monitor = False

        self.turbo = None

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 10 * 60,
        }
        self.agent.register_feed('pfeiffer_turbo',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init(self, session, params):
        """init(auto_acquire=False)

        **Task** - Initialize the connection to the turbo controller.

        Parameters
        ----------
        auto_acquire: bool, optional
            Default is False. Starts data acquisition after initialization
            if True.
        """

        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.turbo = PfeifferTC400(self.ip_address,
                                           self.port_number,
                                           self.turbo_address)
            except socket.timeout as e:
                self.log.error("Turbo Controller timed out"
                               + f"during connect with error {e}")
                return False, "Timeout"
            self.log.info("Connected to turbo controller")

        # Start data acquisition if requested in site-config
        auto_acquire = params.get('auto_acquire', False)
        if auto_acquire:
            self.agent.start('acq')

        return True, 'Initialized Turbo Controller.'

    @ocs_agent.param('test_mode', default=False, type=bool)
    @ocs_agent.param('wait', default=1, type=float)
    def acq(self, session, params):
        """acq(wait=1, test_mode=False)

        **Process** - Continuously monitor turbo motor temp and rotation speed
        and send info to aggregator.

        The ``session.data`` object stores the most recent published values
        in a dictionary. For example::

            session.data = {
                'timestamp': 1598626144.5365012,
                'block_name': 'turbo_output',
                'data': {
                    "Turbo_Motor_Temp": 40.054,
                    "Rotation_Speed": 823.655,
                    "Error_Code": "Err001",
                }
            }

        Parameters
        ----------
        wait: float, optional
            time to wait between measurements [seconds]. Default=1s.

        """
        self.monitor = True

        while self.monitor:
            with self.lock.acquire_timeout(1) as acquired:
                if acquired:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'turbo_output',
                        'data': {}
                    }

                    try:
                        data['data']["Turbo_Motor_Temp"] = self.turbo.get_turbo_motor_temperature()
                        data['data']["Rotation_Speed"] = self.turbo.get_turbo_actual_rotation_speed()
                        data['data']['Error_Code'] = self.turbo.get_turbo_error_code()
                    except ValueError as e:
                        self.log.error(f"Error in collecting data: {e}")
                        continue

                    self.agent.publish_to_feed('pfeiffer_turbo', data)

                    # Allow this process to be queried to return current data
                    session.data = data

                else:
                    self.log.warn("Could not acquire in monitor turbo")

            time.sleep(params['wait'])

            if params['test_mode']:
                break

        return True, "Finished monitoring turbo"

    def _stop_acq(self, session, params):
        """Stop monitoring the turbo output."""
        if self.monitor:
            self.monitor = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    @ocs_agent.param('_')
    def turn_turbo_on(self, session, params):
        """turn_turbo_on()

        **Task** - Turns the turbo on.

        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                ready = self.turbo.ready_turbo()
                if not ready:
                    return False, "Setting to ready state failed"
                time.sleep(1)
                on = self.turbo.turn_turbo_motor_on()
                if not on:
                    return False, "Turbo unable to be turned on"
            else:
                return False, "Could not acquire lock"

        return True, 'Turned turbo on'

    @ocs_agent.param('_')
    def turn_turbo_off(self, session, params):
        """turn_turbo_off()

        **Task** - Turns the turbo off.

        """

        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                off = self.turbo.turn_turbo_motor_off()
                if not off:
                    return False, "Turbo unable to be turned off"
                time.sleep(1)
                unready = self.turbo.unready_turbo()
                if not unready:
                    return False, "Setting to ready state failed"
            else:
                return False, "Could not acquire lock"

        return True, 'Turned turbo off'

    @ocs_agent.param('_')
    def acknowledge_turbo_errors(self, session, params):
        """acknowledge_turbo_errors()

        **Task** - Sends an acknowledgment of the error code to the turbo.

        """
        with self.lock.acquire_timeout(1) as acquired:
            if acquired:
                self.turbo.acknowledge_turbo_errors()
            else:
                return False, "Could not acquire lock"

        return True, 'Acknowledged Turbo Errors.'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address', type=str, help="Serial-to-ethernet "
                        + "converter ip address")
    pgroup.add_argument('--port-number', type=int, help="Serial-to-ethernet "
                        + "converter port")
    pgroup.add_argument('--turbo-address', type=int, help="Internal address "
                        + "used by power supplies")
    pgroup.add_argument('--mode', type=str, help="Set to acq to run acq on "
                        + "startup")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = site_config.add_arguments()

    # Get the default ocs agrument parser
    parser = make_parser()
    args = site_config.parse_args(agent_class='PfeifferTC400Agent',
                                  parser=parser,
                                  args=args)

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = PfeifferTC400Agent(agent,
                           args.ip_address,
                           int(args.port_number),
                           int(args.turbo_address))

    agent.register_task('init', p.init, startup=init_params)
    agent.register_task('turn_turbo_on', p.turn_turbo_on)
    agent.register_task('turn_turbo_off', p.turn_turbo_off)
    agent.register_task('acknowledge_turbo_errors', p.acknowledge_turbo_errors)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
