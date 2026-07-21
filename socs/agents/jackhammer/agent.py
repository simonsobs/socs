import argparse
import os
import traceback

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

txaio.use_twisted()


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
        The session data object reports the current step of the hammer
        sequence::

            >>> response.session['data']
            {'status': 'done',
             'slots': [2, 3],
             'reboot': True}
        """
        from sodetlib.hammers.jackhammer import hammer

        with self.lock.acquire_timeout(10, job='hammer') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            session.data = {
                'status': 'running',
                'slots': params.get('slots'),
                'reboot': not params['no_reboot'],
                'error': None,
            }

            try:
                hammer(
                    slots=params.get('slots'),
                    no_reboot=params['no_reboot'],
                    no_dump=params['no_dump'],
                    skip_setup=params['skip_setup'],
                    dump_rogue=params['dump_rogue'],
                )
            except Exception as e:
                self.log.error("Hammer failed: {error}", error=e)
                session.data['status'] = 'error'
                session.data['error'] = traceback.format_exc()
                return False, f"Hammer failed: {e}"

            session.data['status'] = 'done'

        reboot_str = "soft" if params['no_reboot'] else "hard"
        return True, f"Successfully {reboot_str}-hammered slots {params.get('slots')}"


def add_agent_args(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    return parser


def main(args=None):
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='JackhammerAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    p = JackhammerAgent(agent)

    agent.register_task('hammer', p.hammer)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
