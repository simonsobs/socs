import os
import time
import txaio
import yaml

from datetime import datetime, timedelta
from os import environ

from ocs import ocs_agent, site_config
from ocs.ocs_client import OCSClient


class HwpSupervisorAgent:
    """HWP Supervisor Agent, for monitoring the conditions of the HWP and
    shutting down when needed.

    This Agent monitors the temperature near the HWP as well as the UPS battery
    state to determine if it is safe to continue to operate the HWP. If it is
    deemed unsafe, the Agent triggers a shutdown procedure, coordinating multiple
    HWP related Agents.

    Parameters:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        configfile (str): Path to HWP Supervisor configuration file.

    Attributes:
        agent (OCSAgent): OCSAgent object from :func:`ocs.ocs_agent.init_site_agent`.
        log (txaio.tx.Logger): Logger object used to log events within the
            Agent.
        configfile (str): Path to HWP Supervisor configuration file.
        clients (dict): OCS Clients for each configured hardware device. Each
            key is an instance-id, the value is the OCSClient object.
        override (bool): True when override_status is used to set the status.
            False once override expires. Defaults to False.
        status (dict): Status dictionary. Returned in monitor's session.data.
            Can be set by override_status.

    """

    def __init__(self, agent, configfile):
        self.agent = agent
        self.log = agent.log
        self.configfile = configfile
        self._config = None  # full config, loaded via load_config()
        self.clients = None
        self._monitor = False  # keeps monitor() loop running
        self.override = False
        self.status = None

        # Register OCS feed
        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('feed_name',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    def init_clients(self, session, params):
        """init_clients()

        **Task** - Initialize the OCS Clients used to monitor the hardware.

        """

        if self._config is None:
            return False, "Cannot initialize clients, config not loaded"

        clients = {}
        print(self._config)
        for _, device in self._config.items():
            try:
                clients[device['instance-id']] = OCSClient(device['instance-id'])
            except KeyError as e:
                self.log.error(f"Agent instance-id not provided for {device}")
                self.log.error(f"{e}")
                return False, "Failed to initialize clients, missing instance-id"

        self.clients = clients

        return True, "Clients intiated"

    @ocs_agent.param('configfile', type=str, default=None)
    def load_config(self, session, params):
        """load_config()

        **Task** - Load the configuration file containing Agent instance-ids,
        monitored fields, and valid ranges.

        Parameters:
            configfile (str): Path to HWP Supervisor configuration file,
                relative to ``$OCS_CONFIG_DIR``.

        """
        # default to path within container
        path = os.environ.get("OCS_CONFIG_DIR", "/config/")

        if params is not None:
            file = params['configfile']
        else:
            file = self.configfile

        filepath = os.path.join(path, file)
        with open(filepath) as f:
            self._config = yaml.safe_load(f)

        return True, f"Configuration file loaded from {filepath}"

    @ocs_agent.param('test_mode', type=bool, default=False)
    def monitor(self, session, params):
        """monitor(test_mode=False)

        **Process** - Monitor the 60 K temperature near the HWP and the UPS
        battery state. Determine the status of whether it is safe to continue
        to operate the HWP.

        Parameters:
            test_mode (bool): Will exit after one iteration of the monitor loop
                if True. Defaults to False.

        Notes:
            The most recent value is stored in the session data object in the
            format::

                >>> response.session['data']
                {"status": "ok", "expires": "2021-12-07 21:30:00", "worry": 0.0}

        """
        session.set_status('running')

        self._monitor = True

        # get the clients we need to monitor
        _lsid = self._config["lakeshore-device"]["instance-id"]
        _upsid = self._config["ups-device"]["instance-id"]

        ls_client = self.clients[_lsid]
        ups_client = self.clients[_upsid]

        while self._monitor:
            # if status is overriden just publish that until it expires
            if self.override:
                expiration = datetime.strptime(self.status["expires"], "%Y-%m-%d %H:%M:%S")
                now = datetime.fromtimestamp(time.time())

                if now > expiration:
                    self.override = False
                    self.status = None
                    continue

                session.data = self.status
                time.sleep(1)
                continue

            # determine real status
            worry = 0
            resp = ls_client.acq.status()

            # check temperature data is recent
            latest_temp_timestamp = resp.session["data"]["timestamp"]
            print(latest_temp_timestamp)
            if time.time() - latest_temp_timestamp > 60:
                worry += 1

            # check temperature value
            _temp_fields = resp.session["data"]["fields"]
            latest_temp = _temp_fields[self._config["lakeshore-device"]["field"]]["T"]
            print(latest_temp)
            # TODO: use "valid-range" from config
            if latest_temp > 40:
                worry += 1

            # check UPS power
            resp = ups_client.acq.status()
            print(resp)
            # TODO: Implement UPS check once UPS agent is written

            if worry > 0:
                status = 'warn'
            else:
                status = 'ok'

            now = datetime.now()
            expiration = (now + timedelta(10)).strftime("%Y-%m-%d %H:%M:%S")
            session.data = {"status": status,
                            "expires": expiration,
                            "worry": worry}

            message = {'block_name': 'supervisor_status',
                       'timestamp': time.time(),
                       'data': session.data}
            self.agent.publish_to_feed('feed_name', message)

            # trigger shutdown
            if worry > 0:
                self.agent.start('shutdown', params={})

            if params['test_mode']:
                break

        self.agent.feeds['feed_name'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def _stop_monitor(self, session, params):
        """Stop monitoring the turbo output."""
        if self._monitor:
            self._monitor = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'monitor is not currently running'

    @ocs_agent.param('status', type=str, choices=['ok', 'warn'])
    @ocs_agent.param('expiration', type=str)
    @ocs_agent.param('worry', type=int)
    def override_status(self, session, params):
        """override_status()

        **Task** - Override the monitor's status and expiration time.

        Parameters:
            status (str): Status state, either 'ok' or 'warn'.
            expiration (str): Expiration time for the override in format
                "%Y-%m-%d %H:%M:%S".
            worry (int): Worry value for override status. Values greater than
                zero are worrisome.

        """
        self.override = True
        self.status = {'status': params['status'],
                       'expires': params['expiration'],
                       'worry': params['worry']}

        return True, f"Overrode status with {self.status}"

    def shutdown(self, session, params):
        """shutdown()

        **Task** - Shutdown the HWP system.

        """
        # make into params?
        WAIT_TIME = 30
        MAX_WAIT = 40
        total_wait = 0  # minutes

        session.set_status('running')

        # grab relevant clients
        _id = self._config['hwp-rotation-agent']['instance-id']
        rotation_agent = self.clients[_id]
        _id = self._config['hwp-gripper-agent']['instance-id']
        gripper_agent = self.clients[_id]

        # perform shutdown operations
        # stop the rotation of hwp
        rotation_agent.set_off()

        # wait for X minutes
        time.sleep(WAIT_TIME * 60)
        total_wait += WAIT_TIME

        # confirm hwp is stopped
        _id = self._config['hwp-encoder-agent']['instance-id']
        encoder_agent = self.clients[_id]

        # check for valid/recent encoder data
        resp = encoder_agent.acq.status()
        if resp.session['data']['approx_hwp_freq'] == -1:
            return False, 'approx_hwp_freq = -1, hwp freq unknown, aborting...'
        if time.time() - resp.session['data']['encoder_last_updated'] > 60:
            return False, 'encoder data is stale, unknown hwp state'

        # wait a few more minutes if hwp hasn't stopped
        while total_wait < MAX_WAIT:
            resp = encoder_agent.acq.status()
            print(resp)

            if resp.session['data']['approx_hwp_freq'] == 0:
                break

            time.sleep(1 * 60)
            total_wait += 1

        # failed to stop, don't grip
        resp = encoder_agent.acq.status()
        if resp.session['data']['approx_hwp_freq'] > 0:
            return False, 'HWP failed to shutdown, still rotating after ' + \
                f'{MAX_WAIT} minutes'

        # grip the hwp in safe position
        gripper_agent.grip_move(mode='PUSH', actuator=0, distance=5)
        gripper_agent.grip_move(mode='PUSH', actuator=1, distance=5)
        gripper_agent.grip_move(mode='PUSH', actuator=2, distance=5)

        return True, 'HWP shutdown procedure completed'


def make_parser(parser_in=None):
    if parser_in is None:
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument('--mode', type=str, default='monitor',
                        choices=['idle', 'monitor'],
                        help="Starting action for the Agent.")
    pgroup.add_argument('--configfile', type=str,
                        help="Path to configuration file, relative to OCS_CONFIG_DIR.")

    return parser_in


if __name__ == '__main__':
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='HwpSupervisorAgent', parser=parser)

    startup = False
    if args.mode == 'monitor':
        startup = True

    agent, runner = ocs_agent.init_site_agent(args)

    barebone = HwpSupervisorAgent(agent, args.configfile)
    agent.register_process(
        'monitor',
        barebone.monitor,
        barebone._stop_monitor,
        startup=startup)
    agent.register_task('shutdown', barebone.shutdown)

    runner.run(agent, auto_reconnect=True)
