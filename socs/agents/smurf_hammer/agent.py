# Code developed with AI assistance.

import argparse
import os
import time
import traceback

import txaio
import zmq
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from sodetlib.hammers.jackhammer import hammer, sys_config

# Registers polled by the monitor process, relative to the rogue root.
CONFIGURED_REG = 'AMCc.SmurfApplication.SystemConfigured'
CONFIGURING_REG = 'AMCc.SmurfApplication.ConfiguringInProgress'


def server_port(slot):
    """Base port of the rogue ZMQ server for a slot (pysmurf convention)."""
    return 9000 + 3 * int(slot)


def read_registers(requests, timeout=2.0, context=None):
    """Read rogue variables from one or more servers, all at once.

    Each request is sent on its own ZMQ request socket and the replies are
    collected under a single deadline, so a pass over six unreachable slots
    costs one ``timeout``, not twelve. This bypasses pysmurf and pyrogue
    entirely (the same protocol sodetlib's jackhammer uses), so it works
    when a slot is degraded and does not hang the way starting a
    ``SmurfControl`` would.

    Parameters
    ----------
    requests : list of (int, str)
        ``(port, path)`` pairs: the base port of the slot's rogue ZMQ
        server (its binary request/reply socket lives at ``port + 1``) and
        the dotted path of the variable, e.g.
        ``AMCc.SmurfApplication.SystemConfigured``.
    timeout : float
        Seconds to wait for all replies.
    context : zmq.Context, optional
        Context to create the sockets from. Defaults to the global instance.

    Returns
    -------
    list
        One entry per request, in order: the variable's value, or ``None``
        if that server did not reply in time, the node does not exist, or
        the server reported an error.
    """
    ctx = context if context is not None else zmq.Context.instance()
    results = [None] * len(requests)
    # Each request gets its own REQ socket: a REQ socket is strictly
    # send-then-receive, so one socket could only carry one request at a
    # time. Several sockets connecting to the same server port is fine; the
    # server's REP socket accepts any number of clients and answers them in
    # arrival order.
    poller = zmq.Poller()
    socks = []
    pending = {}  # socket -> index into requests, for the unanswered ones
    try:
        for i, (port, path) in enumerate(requests):
            sock = ctx.socket(zmq.REQ)
            socks.append(sock)
            sock.setsockopt(zmq.LINGER, 0)  # discard undelivered on close
            sock.connect(f"tcp://localhost:{port + 1}")
            sock.send_pyobj(
                {'path': path, 'attr': 'get', 'args': [], 'kwargs': {}})
            poller.register(sock, zmq.POLLIN)
            pending[sock] = i

        # Wait for the replies with a single deadline. poll(ms) blocks until
        # at least one registered socket has a message waiting (POLLIN) or
        # the time runs out, and returns the sockets that are ready. It does
        # not read them; that is done below with NOBLOCK, which cannot stall
        # because the poller has just said data is there. Several sockets can
        # become ready in one wakeup, and sockets that have answered are
        # dropped from the poller so later wakeups only wait on the rest.
        # The time budget is recomputed from the deadline on every pass, so
        # the whole loop takes at most `timeout` however many wakeups there
        # are. Anything still unanswered at the deadline keeps its None.
        deadline = time.monotonic() + timeout
        while pending:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            for sock, _ in poller.poll(remaining * 1000):
                i = pending.pop(sock)
                poller.unregister(sock)
                try:
                    resp = sock.recv_pyobj(zmq.NOBLOCK)
                except zmq.ZMQError:
                    continue
                # rogue answers a failed operation with a pickled Exception,
                # and an unknown path with None.
                if not isinstance(resp, Exception):
                    results[i] = resp
    finally:
        for sock in socks:
            sock.close()
    return results


def read_register(port, path, timeout=2.0, context=None):
    """Read one rogue variable; see :func:`read_registers`."""
    return read_registers([(port, path)], timeout=timeout, context=context)[0]


class SmurfHammerAgent:
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
        self.slot_order = list(sys_config['slot_order'])

        self.agent.register_feed('system_configured',
                                 record=True,
                                 buffer_time=1)

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
             'failed_slots': {3: 'Timed out after 180s waiting for server connection on port 9009'},
             'error': None}
        """

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
            self.log.error(
                "Hammer failed: {error}\n{traceback}",
                error=e,
                traceback=traceback.format_exc()
            )
            session.data['error'] = f"{e}"
            return False, f"Hammer failed: {e}"

        session.data['succeeded_slots'] = result['succeeded']
        session.data['failed_slots'] = result['failed']

        succeeded = result['succeeded']
        failed = result['failed']

        if not succeeded:
            return False, f"All slots failed: {failed}"
        if failed:
            return False, (
                f"Partial success: slots {succeeded} succeeded, "
                f"slots {list(failed.keys())} failed"
            )
        return True, f"Successfully hammered slots {succeeded}"

    @ocs_agent.param('_')
    def monitor(self, session, params):
        """monitor()

        **Process** - Continuously monitor the configuration status of
        each SMuRF slot by reading two registers from its rogue server:

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
        value and ``None`` means the slot's rogue server did not answer
        (slot unreachable).
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

            # one request per register per slot, all in flight together
            requests = []
            for slot in self.slot_order:
                requests.append((server_port(slot), CONFIGURED_REG))
                requests.append((server_port(slot), CONFIGURING_REG))
            values = read_registers(requests)

            for i, slot in enumerate(self.slot_order):
                val_configured = values[2 * i]
                val_configuring = values[2 * i + 1]

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
    args = site_config.parse_args(agent_class='SmurfHammerAgent',
                                  parser=parser,
                                  args=args)

    startup = not args.no_processes

    agent, runner = ocs_agent.init_site_agent(args)
    p = SmurfHammerAgent(agent)

    agent.register_process('monitor',
                           p.monitor,
                           p._stop_monitor,
                           blocking=True,
                           startup=startup)

    agent.register_task('hammer', p.hammer)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
