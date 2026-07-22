import argparse
import os
import traceback

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class JackhammerAgent:
    """Agent to execute the sodetlib jackhammer hammer sequence.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent.
    """

    def __init__(self, agent):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

    @ocs_agent.param('slots', default=None)
    @ocs_agent.param('no_reboot', default=False, type=bool)
    @ocs_agent.param('no_dump', default=False, type=bool)
    @ocs_agent.param('skip_setup', default=False, type=bool)
    @ocs_agent.param('dump_rogue', default=False, type=bool)
    def hammer(self, session, params):
        """hammer(slots=None, no_reboot=False, no_dump=False, \
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
        no_dump : bool
            If True, skip dumping docker logs before hammering.
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
            }

            try:
                result = hammer(
                    slots=params['slots'],
                    no_reboot=params['no_reboot'],
                    no_dump=params['no_dump'],
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


def main(args=None):
    # set up logging
    txaio.use_twisted()
    log = txaio.make_logger()
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    args = site_config.parse_args(agent_class='JackhammerAgent',
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    p = JackhammerAgent(agent)

    agent.register_task('hammer', p.hammer)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
