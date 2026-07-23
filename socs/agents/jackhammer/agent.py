import argparse
import os
import time
import traceback

import epics
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class JackhammerAgent:
    """Agent to execute the sodetlib jackhammer hammer sequence and
    monitor the configured status of each SMuRF slot.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent.
    """

    def __init__(self, agent):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self._monitor_running = False

        # get slots from config file
        from sodetlib.hammers.jackhammer import sys_config
        self.slot_order = list(sys_config['slot_order'])

        self.agent.register_feed('system_configured',
                                 record=True,
                                 buffer_time=0)

    @ocs_agent.param('slots', default=None)
    @ocs_agent.param('no_reboot', default=False, type=bool)
    @ocs_agent.param('dump_logs', default=False, type=bool)
    @ocs_agent.param('skip_setup', default=False, type=bool)
    @ocs_agent.param('dump_rogue', default=False, type=bool)
    def hammer(self, session, params):
        """hammer(slots=None, no_reboot=False, dump_logs=False, \
                  skip_setup=False, dump_rogue=False)

        **Task** - Execute the jackhammer hammer sequence to reset and
        reconfigure SMuRF slots. This replicates the ``jackhammer hammer``
        CLI command.

        Individual slot failures are isolated so that the remaining
        slots can still complete successfully.

        Parameters
        ----------
        slots : list of int, optional
            Slot numbers to hammer. Defaults to all slots defined in
            the sys_config.
        no_reboot : bool
            If True, perform a soft reset without rebooting the carriers.
        dump_logs : bool
            If True, dump docker logs before hammering.
        skip_setup : bool
            If True, skip pysmurf setup after reboot.
        dump_rogue : bool
            If True, dump the rogue tree before hammering.

        Notes
        -----
        The session data object reports per-slot results::

            >>> response.session['data']
            {'slots': [2, 3],
             'reboot': True,
             'succeeded_slots': [2],
             'failed_slots': {3: 'EPICS connection timed out ...'},
             'error': None}
        """
        from sodetlib.hammers.jackhammer import hammer

        with self.lock.acquire_timeout(10, job='hammer') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            session.data = {
                'slots': params.get('slots'),
                'reboot': not params['no_reboot'],
                'succeeded_slots': [],
                'failed_slots': {},
                'error': None,
                'timestamp': time.time(),
            }

            try:
                result = hammer(
                    slots=params['slots'],
                    no_reboot=params['no_reboot'],
                    no_dump=not params['dump_logs'],
                    skip_setup=params['skip_setup'],
                    dump_rogue=params['dump_rogue'],
                )
            except Exception as e:
                self.log.error("Hammer failed: {error}", error=e)
                session.data['error'] = traceback.format_exc()
                return False, f"Hammer failed: {e}"

            session.data['succeeded_slots'] = result['succeeded']
            session.data['failed_slots'] = result['failed']

        succeeded = result['succeeded']
        failed = result['failed']

        if not succeeded:
            return False, f"All slots failed: {failed}"
        if failed:
            return True, (
                f"Partial success: slots {succeeded} succeeded, "
                f"slots {list(failed.keys())} failed"
            )
        return True, f"Successfully hammered slots {succeeded}"

    @ocs_agent.param('_')
    def monitor(self, session, params):
        """monitor()

        **Process** - Continuously monitor the configuration status of
        each SMuRF slot by querying two EPICS registers:

        - ``AMCc.SmurfApplication.SystemConfigured`` — whether setup
          has completed successfully.
        - ``AMCc.SmurfApplication.ConfiguringInProgress`` — whether
          setup is currently running.

        Notes
        -----
        The session data object reports per-slot status::

            >>> response.session['data']
            {'timestamp': 1721234567.0,
             'slots': {
                 2: {'configured': True, 'configuring': False},
                 3: {'configured': False, 'configuring': True},
                 5: {'configured': None, 'configuring': None},
             }}

        For each register, ``True``/``False`` reflect the register
        value and ``None`` means the EPICS query timed out (slot
        unreachable).
        """
        self._monitor_running = True
        session.data = {}

        while self._monitor_running:
            slot_status = {}
            start = time.time()
            feed_data = {
                'block_name': 'system_configured',
                'timestamp': start,
                'data': {},
            }

            for slot in self.slot_order:
                epics_root = f'smurf_server_s{slot}'
                pv_configured = f'{epics_root}:AMCc:SmurfApplication:SystemConfigured'
                pv_configuring = f'{epics_root}:AMCc:SmurfApplication:ConfiguringInProgress'

                val_configured = epics.caget(pv_configured, timeout=5)
                val_configuring = epics.caget(pv_configuring, timeout=5)

                if val_configured is None:
                    configured = None
                    feed_data['data'][f'configured_s{slot}'] = -1
                else:
                    configured = bool(int(val_configured))
                    feed_data['data'][f'configured_s{slot}'] = int(configured)

                if val_configuring is None:
                    configuring = None
                    feed_data['data'][f'configuring_s{slot}'] = -1
                else:
                    configuring = bool(int(val_configuring))
                    feed_data['data'][f'configuring_s{slot}'] = int(configuring)

                slot_status[slot] = {
                    'configured': configured,
                    'configuring': configuring,
                }

            session.data = {
                'timestamp': feed_data['timestamp'],
                'slots': slot_status,
            }

            if feed_data['data']:
                self.agent.publish_to_feed('system_configured', feed_data)

            self.log.debug(
                "Slot status: {status}", status=slot_status
            )

            # aim for 10s between samples
            wait = 10 - (time.time() - start)
            if wait > 0:
                time.sleep(wait)

        return True, 'Monitor exited cleanly.'

    def _stop_monitor(self, session, params):
        self._monitor_running = False
        session.set_status('stopping')
        return True, 'Stopping monitor.'


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument('--no-processes', action='store_true',
                        default=False,
                        help="Do not auto-start the monitor process.")
    return parser_in


def main(args=None):
    # set up logging
    txaio.use_twisted()
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='JackhammerAgent',
                                  parser=parser,
                                  args=args)

    startup = not args.no_processes

    agent, runner = ocs_agent.init_site_agent(args)
    p = JackhammerAgent(agent)

    agent.register_process('monitor',
                           p.monitor,
                           p._stop_monitor,
                           blocking=False,
                           startup=startup)

    # restrict access to level 2
    agent.register_task('hammer', p.hammer, min_privs=2)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
