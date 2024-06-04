import argparse
from os import environ

import requests
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock


class UCSCRadiometerAgent:
    """Monitor the PWV Flask Server.

    Parameters
    ----------
    agent : OCS Agent
        OCSAgent object which forms this Agent
    url : str
        url of the radiometer web server on the internet

    """

    def __init__(self, agent, url):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.url = url

        self.take_data = False

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
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from PWV Flask Server

        Parameters
        ----------
        test_mode : bool, option
            Run the Process loop only once. Meant only for testing.
            Default is False.

        Notes
        -----
        The most recent data collected is stored in session data in the
        following structure::

            >>> response.session['data']
            {'timestamp': 1678820419.0,
             'pwv': 0.49253026985972237}

        """
        pm = Pacemaker(1 / 60, quantize=False)

        self.take_data = True

        while self.take_data:
            try:
                r = requests.get(self.url, timeout=60)
            except ValueError:
                pm.sleep()
                continue
            except requests.exceptions.ConnectionError as e:
                self.log.warn(f"Connection error occured: {e}")
                pm.sleep()
                continue
            except requests.exceptions.Timeout as e:
                self.log.warn(f"Timeout exception occurred: {e}")
                pm.sleep()
                continue
            data = r.json()
            last_pwv = data['pwv']
            last_timestamp = data['timestamp']

            pwvs = {'block_name': 'pwvs',
                    'timestamp': last_timestamp,
                    'data': {'pwv': last_pwv}
                    }

            if self.last_published_reading is not None:
                if last_timestamp > self.last_published_reading[1]:
                    self.agent.publish_to_feed('pwvs', pwvs)
                    self.last_published_reading = (last_pwv, last_timestamp)
            else:
                self.agent.publish_to_feed('pwvs', pwvs)
                self.last_published_reading = (last_pwv, last_timestamp)

            session.data = {"timestamp": last_timestamp,
                            "pwv": last_pwv}

            if params['test_mode']:
                break
            else:
                pm.sleep()

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        self.take_data = False
        return True, 'Stopping acq process'


def add_agent_args(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument("--url", type=str, help="url for radiometer web server")
    pgroup.add_argument("--test-mode", action='store_true',
                        help="Determines whether agent runs in test mode."
                        "Default is False.")
    return parser


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='UCSCRadiometerAgent', parser=parser, args=args)

    # test params
    test_params = {'test_mode': False}
    if args.test_mode:
        test_params = {'test_mode': True}

    agent, runner = ocs_agent.init_site_agent(args)
    pwv_agent = UCSCRadiometerAgent(agent, args.url)

    agent.register_process('acq', pwv_agent.acq, pwv_agent._stop_acq, startup=test_params)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
