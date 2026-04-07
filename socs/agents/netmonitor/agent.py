import socket
import time
from os import environ

import txaio
from ocs import ocs_agent, ocs_twisted, site_config

from . import drivers

txaio.use_twisted()


class NetMonitorAgent:
    def __init__(self, agent, ping_config=None):
        self.agent = agent
        self.log = agent.log

        self.ping_config = ping_config

        # Register feed
        agg_params = {
            'frame_length': 60.,
        }
        self.agent.register_feed('pings',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq(test_mode=False, degradation_period=None)

        **Process** - Acquire data and write to the feed.

        Parameters:
            test_mode (bool, optional): Run the acq Process loop only once.
                This is meant only for testing. Default is False.

        Notes:
            The most recent fake values are stored in the session data object in
            the format::

                >>> response.session['data']
                {"fields":
                    {"channel_00": 0.10250430068515494,
                     "channel_01": 0.08550903376216404,
                     "channel_02": 0.10481891991693446,
                     "channel_03": 0.10793263271024509},
                 "timestamp":1600448753.9288929}

            The channels kept in fields are the 'faked' data, in a similar
            structure to the Lakeshore agents. 'timestamp' is the last time
            these values were updated.

        """
        pinger = drivers.Pinger()
        for host in self.ping_config.hosts:
            pinger.add_targets([host])
        pinger.set_intervals([60, 3600])

        ping_interval = 10
        report_cadence = 6
        pm = ocs_twisted.Pacemaker(1 / ping_interval)
        session.data = {}

        to_report = 0
        while session.status == 'running':
            pm.sleep()
            pinger.poll()
            st = pinger.get_stats()
            session.data.update({
                'timestamp': time.time(),
                'interval': ping_interval,
                'cadence': report_cadence,
                'windows': st,
            })
            if to_report := to_report - 1 <= 0:
                fields = {}
                for stblock in st:
                    prefix = f'pingfrac_{stblock["window_size"]:d}s_'
                    for k, vs in stblock['hosts'].items():
                        fields[prefix + k.replace('-', '_').replace('.', '_')] = vs['up_fraction']
                data = {
                    'timestamp': time.time(),
                    'data': fields
                }
                print(data)
                session.app.publish_to_feed('pings', data)
                to_report = report_cadence
            if params['test_mode']:
                break

        self.agent.feeds['pings'].flush_buffer()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        session.set_status('stopping')
        return True, 'Requested process stop.'


def add_agent_args(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--config-file")
    return parser_in


def main(args=None):
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='NetMonitorAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    ping_config = drivers.PingConfig.from_file(args.config_file)
    for host in ping_config.hosts:
        if host.ip in ['', None]:
            host.ip = socket.gethostbyname(host.name)

    netmon = NetMonitorAgent(agent, ping_config=ping_config)
    agent.register_process('acq', netmon.acq, netmon._stop_acq,
                           blocking=True, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
