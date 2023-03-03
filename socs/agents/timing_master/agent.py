import argparse
import txaio
import os
import time
from epics import PV

from ocs.ocs_twisted import Pacemaker
from ocs import site_config, ocs_agent


diagnostic_root = 'TPG:SMRF:1'
regs = [
    'COUNTPLL', 'COUNT186M', 'COUNTSYNCERR', 'COUNTINTV', 'COUNTBRT',
    'COUNTTXCLK', 'DELTATXCLK', 'RATETXCLK'
]
regs_full = {
    r: f'{diagnostic_root}:{r}' for r in regs
}


class TimingMasterAgent:
    """
    Agent to monitor diagnostic variables for the SMuRF Timing Master.
    """
    def __init__(self, agent, args):
        self.agent = agent
        self.log = agent.log
        self.sleep_time = args.sleep_time
        self.pvs = {
            k: PV(r) for k, r in regs_full.items()
        }
        self.timeout = args.timeout
        self.use_monitor = args.use_monitor
        agent.register_feed('diagnostics', record=True)
    
    def run(self, session, params):
        """run()
        
        **Process** -- Main loop for the timing master. This queries diagnostic
        PVs and publishes data.
        """
        pacemaker = Pacemaker(1./self.sleep_time)
        session.set_status('running')
        while session.status in ['starting', 'running']:
            data = {}
            for name, pv in self.pvs.items():
                res = pv.get(timeout=self.timeout, use_monitor=self.use_monitor)
                if res is None:
                    self.log.error("Timeout for PV: {name}", name=name)
                    break
                data[name] = res
            else:
                msg = {
                    'timestamp': time.time(),
                    'block_name': 'diagnostics',
                    'data': data
                }
                self.agent.publish_to_feed('diagnostics', msg)
            pacemaker.sleep()

        return True, 'Run process has been stopped'

    def _stop(self, session, params=None):
        session.set_status('stopping')


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--timeout', type=float, default=3.,
                        help='Timeout for epics caget calls')
    pgroup.add_argument('--sleep-time', type=float, default=30.,
                        help="Time to sleep between loop iterations")
    pgroup.add_argument('--use-monitor', action='store_true',
                        help="Use the epics monitored value. If False, will "
                             "re-poll for every get call.")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args("TimingMasterAgent", parser=parser, args=args)
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))
    agent, runner = ocs_agent.init_site_agent(args)
    timing_master = TimingMasterAgent(agent, args)
    agent.register_process('run', timing_master.run, timing_master._stop, startup=True)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()