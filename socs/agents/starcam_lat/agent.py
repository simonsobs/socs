import argparse
import time
from os import environ

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

from socs.agents.starcam_lat.drivers import StarcamHelper


class StarcamAgent:
    """Communicate with the starcam.

    Parameters
    ----------
    agent: OCSAgent
        OCSAgent object for this agent.
    ip_address: str
        IP address of starcam computer.
    port: int
        Port of the starcam computer.

    Attributes
    ----------
    agent: OCSAgent
        OCSAgent object for this agent.
    take_data: bool
        Tracks whether or not the agent is trying to retrieve data from the
        starcam computer. Setting to False stops this process.
    log: txaio.tx.Logger
        txaio logger object, created by OCSAgent.
    """

    def __init__(self, agent, ip_address, port):
        self.agent = agent
        self.log = agent.log
        self.take_data = False
        self.lock = TimeoutLock()
        self.starcam = StarcamHelper(ip_address, port)

        agg_params = {'frame_length': 60}
        self.agent.register_feed("starcamera", record=True,
                                 agg_params=agg_params, buffer_time=1)

    @ocs_agent.param('_')
    def send_commands(self, session, params=None):
        """send_commands()

        **Process** - Pack and send camera and astrometry-related commands to
        the starcam.

        """
        with self.lock.acquire_timeout(job='send_commands') as acquired:
            if not acquired:
                self.log.warn(f"Could not start task because "
                              f"{self.lock.job} is already running.")
                return False, "Could not acquire lock."
            self.log.info("Sending commands.")
            self.starcam.send_cmds()
            self.log.info("Commands sent to camera.")
        return True, "Sent commands to the starcam."

    @ocs_agent.param('_')
    def acq(self, session, params=None):
        """acq()

        **Process** - Acquire data from the starcam.

        Notes
        -----
        An example of the updated session data::

            >>> response.session['data']
            {'timestamp': 1734668749.643134,
             'block_name': 'astrometry',
             'data':
                 {'c_time': 1734668749,
                  'gmt': Dec 20 04:25:49,
                  'blob_num': 6,
                  'obs_ra': 87.339171,
                  'astrom_ra': 87.391578,
                  'obs_dec': -22.956034,
                  'astrom_dec': -22.964401,
                  'fr': 36.591606,
                  'ps': 6.220203,
                  'alt': 89.758799574147034,
                  'az': 270.55842800340095,
                  'ir': 54.068988,
                  'astrom_solve_time': 507.617792,
                  'camera_time': 508.128256,
                  }
            }

        """
        with self.lock.acquire_timeout(timeout=10, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already "
                              "running".format(self.lock.job))
                return False, "Could not acquire lock."
            session.set_status('running')
            self.log.info("Starting acquisition.")
            self.take_data = True
            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'astrometry',
                    'data': {}
                }
                try:
                    astrom_data_dict = self.starcam.get_astrom_data()
                    if session.degraded:
                        self.log.info("Connection re-established.")
                        session.degraded = False
                except ConnectionError:
                    self.log.error("Failed to get data from star camera. Check network connection.")
                    session.degraded = True
                    time.sleep(1)
                    continue
                # update the data dictionary+session and publish
                data['data'].update(astrom_data_dict)
                session.data.update(data['data'])
                self.agent.publish_to_feed('starcamera', data)

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params):
        """
        Stops acq process.
        """
        ok = False
        if self.take_data:
            session.set_status('stopping')
            self.take_data = False
            ok = True
        return (ok, {True: 'Requested process to stop.',
                     False: 'Failed to request process stop.'}[ok])


def add_agent_args(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument("--ip-address", type=str,
                        help="IP address of starcam computer")
    pgroup.add_argument("--port", default="8000", type=int,
                        help="Port of starcam computer")
    return parser


def main(args=None):
    # for logging
    txaio.use_twisted()
    txaio.make_logger()

    # start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class="StarcamAgent", parser=parser)
    agent, runner = ocs_agent.init_site_agent(args)
    starcam_agent = StarcamAgent(agent, ip_address=args.ip_address,
                                 port=args.port)
    agent.register_task('send_commands', starcam_agent.send_commands,
                        startup=True)
    agent.register_process('acq', starcam_agent.acq, starcam_agent._stop_acq)
    runner.run(agent, auto_reconnect=False)


if __name__ == '__main__':
    main()
