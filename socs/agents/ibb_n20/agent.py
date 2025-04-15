import argparse
import os
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet.defer import inlineCallbacks

import asyncio
import telnetlib

txaio.use_twisted()


class ibbn20Agent:
    """Monitor the ibb_n20 via Telnet.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    ip : str
        IP address of the ibb_n20
    port : int
        Telnet port to issue GETs to, default to 23
    verbosity : str
        Verbosity of ibb_n20 output

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing telnet GET commands
        to the device. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, ip, port, verbosity):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.lastGet = 0
        self.sample_period = 30

        self.verbosity = verbosity
        self.establish_connection(ip, port)
        self.connected = True

        agg_params = {'frame_length': 60}
        self.agent.register_feed('ibb_n20',
                                 record=True,
                                 agg_params=agg_params)

    def establish_connection(self, ip, port):
        try:
            self.tn = telnetlib.Telnet(ip, port)
            output = self.read(b"User Name:")
            if self.verbosity:
                print(output)
            self.tn.write(b"admin\n")
            output = self.read(b"Password:")
            if self.verbosity:
                print(output)
            self.tn.write(b"admin\n")
            output = self.read()
            if self.verbosity:
                print(output)
        except Exception as e:
            print(e)


    def read(self, until=b"iBootBar >"):
        output = self.tn.read_until(until)
        output = output.decode('utf-8')
        return output


    def get_outlets(self):
        self.tn.write(b"get outlets\n")
        output = self.read()
        if self.verbosity:
            print(output)
        outlets = [{'N': 1, 'F': 0}.get(v) for v in output.split('\n')[2][29:51:3]]
        current = float(output.split('\n')[2][55:58])
        status = {'current': current}
        for i, s in enumerate(outlets):
            status[f'outletstatus_{i + 1}'] = s
        return status


    @ocs_agent.param('outlet', choices=[1, 2, 3, 4, 5, 6, 7, 8])
    @ocs_agent.param('state', choices=['on', 'off', 'cycle'])
    @inlineCallbacks
    def set_outlet(self, session, params=None):
        """set_outlet(outlet, state)

        **Task** - Set a particular outlet to on/off.

        Parameters
        ----------
        outlet : int
            Outlet number to set. Choices are 1-8 (physical outlets).
        state : str
            State to set outlet to, which may be 'on', 'off' or 'cycle'
        """
        with self.lock.acquire_timeout(3, job='set_outlet') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            self.tn.write(b('set outlet {} {}\n'.\
                format(params['outlet'], params['state'])))
            output = self.read()
            self.log.debug(output)

        # Foce GET status commands by rewinding the lastGet time by sample period
        self.lastGet = self.lastGet - self.sample_period

        return True, 'Set outlet {} to {}'.\
            format(params['outlet'], params['state'])


    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()

        **Process** - Acqure data from the ibb_n20 via Telnet.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'fields':
                {'current': 4.4,
                 1: {'status': 1, 'name': 'outlet_1'},
                 2: {'status': 0, 'name': 'outlet_2'},
                 ...
                },
            'timestamp': 1744756162.206159}
        """

        self.is_streaming = True
        while self.is_streaming:
            if not self.connected:
                self.log.info('Trying to reconnect.')

            read_time = time.time()

            # Check if sample period has passed before getting status
            if (read_time - self.lastGet) < self.sample_period:
                continue

            current_time = time.time()
            data = {'timestamp': current_time,
                    'block_name': 'ibb_n20',
                    'data': {}}
            status = self.get_outlets()
            data['data'] = status
            self.agent.publish_to_feed('ibb_n20', data)

            status_dict = {'current': status['current']}
            for i in range(1, 9):
                status_dict[i] = {
                    'status': status[f'outletstatus_{i}'],
                    'name': f'outlet_{i}',
                }
            session.data['timestamp'] = current_time
            session.data['fields'] = status_dict

            self.lastGet = time.time()

        self.agent.feeds['ibb_n20'].flush_buffer()
        return True, "Finished Recording"


    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        if self.is_streaming:
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
    pgroup.add_argument("--address", default='192.168.13.24', help="Address to listen to.")
    pgroup.add_argument("--port", default=23,
                        help="Port to listen on.")
    pgroup.add_argument("--mode", default='acq')
    pgroup.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="Verbosity level.",
    )

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ibbn20Agent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = ibbn20Agent(
        agent,
        ip=args.address,
        port=int(args.port),
        verbosity=args.verbose,
    )

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params)
    agent.register_task("set_outlet", p.set_outlet, blocking=False)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
    pgroup.add_argument("--lock-outlet", nargs='+', type=int,
                        help="List of outlets to lock on startup.")
