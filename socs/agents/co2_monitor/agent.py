import argparse
import os
import socket
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

import socs.agents.co2_monitor.drivers.co2_serial as co2

# For logging
txaio.use_twisted()


class CO2MonitorAgent:
    """OCS agent for HWP encoder DAQ using Beaglebone Black

    Attributes
    ----------
    rising_edge_count : int
       clock count values for the rising edge of IRIG reference marker,
       saved for calculating the beaglebone clock frequency
    irig_time : int
       unix timestamp from IRIG

    """

    def __init__(self, agent, ip, port):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port
        self._initialized = False

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('co2_monitor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_connection(self, session, params):
        """init_connection(auto_acquire=False, force=False)

        **Task** - Initialize connection to CO2 monitor
        Controller.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.
            force (bool, optional): Force initialization, even if already
                initialized. Defaults to False.

        """

        with self.lock.acquire_timeout(0, job='init_connection') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not run init_connection because {} is already running'.format(self.lock.job))
                return False, 'Could not acquire lock'

            try:
                self.co2 = co2.CO2(ip=self.ip, port=self.port)
                self.log.info('Connected to PID controller')
            except socket.timeout as e:
                self.log.error(f'Could not establish connection to CO2 monitor, with error {e}')
                return False, 'Unable to connect to CO2 monitor'

        self._initialized = True

        # Start 'acq' Process if requested
        if params['auto_acquire']:
            self.agent.start('acq')

        return True, 'Connection to CO2 monitor established'

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params):
        """acq(test_mode=False)

        **Process** - Read data from CO2 monitor.

        Parameters
        ----------
        test_mode : bool, optional
            Run the Process loop only once. Meant only for testing.
            Default is False.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            # for each camera
            {'location1': {'location': 'location1',
                         'last_attempt': 1701983575.032506,
                         'connected': True,
                         'address': '10.10.10.41'},
             'location2': ...
            }
        """

        session.set_status('running')
        self.is_streaming = True

        while self.take_data:
            data = {'timestamp': time.time(),
                    'block_name': 'co2_monitor',
                    'data': {}}

            try:
                values = self.co2.get_values()

                data['data']['co2_concentration'] = values[0]
                data['data']['air_temp'] = values[1]
                data['data']['relative_humidity'] = values[2]
                data['data']['dew_point_temp'] = values[3]
                data['data']['wet_bulb_temp'] = values[4]
            except BaseException:
                time.sleep(1)
                continue

            self.agent.publish_to_feed('co2_monitor', data)
            self.log.debug("{msg}", msg=data)

            session.data = {'co2_concentration': values[0],
                            'air_temp': values[1],
                            'relative_humidity': values[2],
                            'dew_point_temp': values[3],
                            'wet_bulb_temp': values[4],
                            'last_updated': time.time()}
            self.log.debug("{data}", data=session.data)

        self.agent.feeds['co2_monitor'].flush_buffer()
        return True, 'Finished recording.'

    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        if self.is_streaming:
            session.set_status('stopping')
            self.is_streaming = False
            return True, "Stopping Recording"
        else:
            return False, "Acq is not currently running"


def add_agent_args(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--ip", help="IP address of CO2 monitor moxa.")
    pgroup.add_argument("--port", help="Port of CO2 monitor moxa.")
    pgroup.add_argument("--mode", choices=['acq', 'test'])

    return parser


# Portion of the code that runs
def main(args=None):
   # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='CO2MonitorAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = CO2MonitorAgent(agent,
                        ip=args.ip,
                        port=args.port)

    agent.register_task('init_connection', p.init_connection,
                        startup=init_params)
    agent.register_process("acq",
                           p.acq,
                           p._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
