import argparse
import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.hi6200.drivers import Hi6200Interface


class Hi6200Agent:
    """
    Agent to connect to the Hi6200 weight controller that measures the weight
    of the LN2 dewar on the SAT platform.

    Parameters:
        ip_address (string): IP address set on the Hi6200
        tcp_port (int): Modbus TCP port of the Hi6200.
                    Default set on the device is 502.
        scale (Hi6200Interface): A driver object that allows
                    for communication with the scale.
    """

    def __init__(self, agent, ip_address, tcp_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.tcp_port = tcp_port
        self.scale = None

        self.monitor = False

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
        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            self.scale = Hi6200Interface(self.ip_address, self.tcp_port)

            self.log.info("Connected to scale.")

        return True, 'Initialized Scale.'

    @ocs_agent.param('wait', type=float, default=1)
    def monitor_weight(self, session, params=None):
        """monitor_weight(wait=1)

        **Process** - Continuously monitor scale gross and net weights.

        Parameters:
            wait (float, optional): Time to wait between measurements
                [seconds].

        """
        self.monitor = True

        pm = Pacemaker(1, quantize=True)
        while self.monitor:

            pm.sleep()
            with self.lock.acquire_timeout(1, job='monitor_weight') as acquired:
                if not acquired:
                    self.log.warn("Could not start monitor_weight because "
                                  + f"{self.lock.job} is already running")
                    return False, "Could not acquire lock."

                data = {
                    'timestamp': time.time(),
                    'block_name': 'weight',
                    'data': {}
                }

                try:
                    # Grab the gross and net weights from the scale.
                    gross_weight = self.scale.read_scale_gross_weight()
                    net_weight = self.scale.read_scale_net_weight()

                    # The above functions return None when an Attribute error
                    # is thrown. If they did not return None and threw no
                    # errors, the data is good.
                    if (gross_weight is not None) and (net_weight is not None):
                        data['data']["Gross"] = gross_weight
                        data['data']["Net"] = net_weight
                        self.agent.publish_to_feed('scale_output', data)

                # Occurs when the scale disconnects.
                except AttributeError as e:
                    self.log.error("Connection with scale failed. Check that "
                                   + f"the scale is connected: {e}")
                    return False, "Monitoring weight failed"

                except ValueError as e:
                    self.log.error("Scale responded with an anomolous number, "
                                   + f"ignorning: {e}")

                except TypeError as e:
                    self.log.error("Scale responded with 'None' and broke the "
                                   + f"hex decoding, trying again: {e}")

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
