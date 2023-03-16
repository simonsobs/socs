import requests
import txaio

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class UCSCRadiometerAgent:
    """Monitor the PWV Flask Server.

    Parameters
    ----------
    agent : OCS Agent
        OCSAgent object which forms this Agent
    url : str
        url of the flask server on the internet
    year : int
        year for the corresponding Julian Day
    """
    def __init__(self, agent, url, year):
        self.agent = agent
        self.url = url
        self.year = year

        self.active = True
        self.log = agent.log
        self.lock = TimeoutLock()
        self.job = None

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('pwvs',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

        self.last_published_reading = None

    @ocs_agent.param('test_mode', default=False, type=bool)
    def start_acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from PWV Flask Server

        Parameters
        ----------
        test_mode : bool, option
            Run the Process loop only once. Meant only for testing.
            Default is False.
        """
        while True:
            r = requests.get(self.url)
            data = r.json()
            last_pwv = data['pwv']
            last_timestamp = data['timestamp']

            pwvs = {'block_name': 'pwvs',
                    'timestamp': last_timestamp,
                    'data': {'pwv': last_pwv}
                    }

            if self.last_published_reading is not None:
                if last_timestamp > self.last_published_reading[0]:
                    self.agent.publish_to_feed('pwvs', pwvs)
                    self.last_published_reading = (last_pwv, last_timestamp)
            else:
                self.agent.publish_to_feed('pwvs', pwvs)
                self.last_published_reading = (last_pwv, last_timestamp)

    def _stop_acq(self, session, params=None):
        ok = False
        with self.lock:
            if self.job == 'acq':
                self.job = '!acq'
                ok = True
            return (ok, {True: 'Requested process stop.', False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--url", type=str, help="url for PWV flask server")
    pgroup.add_argument("--year", type=int, help="year for Julian Day PWV measurement")
    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='UCSCRadiometerAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    pwv_agent = UCSCRadiometerAgent(agent, args.url, args.year)

    agent.register_process('acq', pwv_agent.start_acq, pwv_agent._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
