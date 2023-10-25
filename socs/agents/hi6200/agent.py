import argparse
import socket
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.hi6200.drivers import Hi6200Interface


class Hi6200Agent:
    def __init__(self, agent, ip_address, tcp_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.job = None
        self.ip_address = ip_address
        self.tcp_port = tcp_port
        self.monitor = False

        self.scale = None

        # Registers Scale Output
        agg_params = {
            'frame_length': 10 * 60,
        }
        self.agent.register_feed('scale_output',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('_')
    def init(self, session, params=None):
        """init()

        **Task** - Initialize connection to the Hi 6200 Weight Sensor.

        """
        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            try:
                self.scale = Hi6200Interface(self.ip_address, self.tcp_port)

            except BaseException:
                self.log.error(f"Some unknown error occurred initializing TCP Server")
                return False, "TCP Failure"
            self.log.info("Connected to scale.")

        return True, 'Initialized Scale.'

    @ocs_agent.param('wait', type=float, default=1)
    def monitor_weight(self, session, params=None):
        """

        **Process** - Continuously monitor scale gross and net weights.

        Parameters:
            wait (float, optional): Time to wait between measurements
                [seconds].
            test_mode (bool, optional): Exit process after single loop if True.
                Defaults to False.

        """
        session.set_status('running')
        self.monitor = True

        while self.monitor:
            with self.lock.acquire_timeout(1) as acquired:
                if acquired:
                    data = {
                        'timestamp': time.time(),
                        'block_name': 'weight',
                        'data': {}
                    }

                    try:

                        data['data']["Gross"] = self.scale.read_scale_gross_weight()
                        data['data']["Net"] = self.scale.read_scale_net_weight()

         #               self.log.info(f"Gross: {data['data']['Gross']} Net: {data['data']['Net']}")

                        self.agent.publish_to_feed('scale_output', data)

                        # Allow this process to be queried to return current data
                        session.data = data

                    except ValueError as e:

                        self.log.error(f"Scale responded with an anomolous number, ignorning: {e}")

                    except AttributeError as e:
                        self.log.error("Scale dropped TCP connection momentarily, trying again: {e}")

                    # Allow this process to be queried to return current data
                    session.data = data

                else:
                    self.log.warn("Could not acquire in monitor_weight")

            time.sleep(params['wait'])

        return True, "Finished monitoring weight"

    def stop_monitoring(self, session, params=None):
        self.monitor = False
        return True, "Stopping current monitor"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--tcp-port')

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='Hi6200Agent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    p = Hi6200Agent(agent, args.ip_address, int(args.tcp_port))

    agent.register_task('init', p.init)

    agent.register_process('monitor_weight', p.monitor_weight, p.stop_monitoring)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
