from twisted.internet import reactor, protocol, threads
from twisted.python.failure import Failure
from twisted.internet.error import ProcessDone, ProcessTerminated
from twisted.internet.defer import inlineCallbacks, Deferred
from autobahn.twisted.util import sleep as dsleep
from twisted.logger import Logger, FileLogObserver

import sys
from typing import Optional
import time
import os
import argparse

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config, ocs_twisted
    from ocs.ocs_agent import log_formatter
    from ocs.ocs_twisted import TimeoutLock


class PysmurfScriptProtocol(protocol.ProcessProtocol):
    """
    The process protocol used to dispatch external Pysmurf scripts, and manage
    the stdin, stdout, and stderr pipelines.

    Arguments
    ---------
    path : str
        Path of script to run.
    log : txaio.tx.Logger
        txaio logger object, used to log stdout and stderr messages.

    Attributes
    -----------
    path : str
        Path of script to run.
    log : txaio.tx.Logger
        txaio logger object, used to log stdout and stderr messages.
    end_status : twisted.python.failure.Failure
        Reason that the process ended.
    """
    def __init__(self, path, log=None):
        self.path = path
        self.log = log
        self.end_status: Optional[Failure] = None

    def connectionMade(self):
        """Called when process is started"""
        self.transport.closeStdin()

    def outReceived(self, data):
        """Called whenever data is received through stdout"""
        if self.log:
            self.log.info("{path}: {data}",
                          path=self.path.split('/')[-1],
                          data=data.strip().decode('utf-8'))

    def errReceived(self, data):
        """Called whenever data is received through stderr"""
        self.log.error(data)

    def processExited(self, status: Failure):
        """Called when process has exited."""

        rc = status.value.exitCode
        if self.log is not None:
            self.log.info("Process ended with exit code {rc}", rc=rc)

        self.deferred.callback(rc)


class PysmurfController:
    """
    Controller object for running pysmurf scripts and functions.

    Arguments
    ---------
    agent: ocs.ocs_agent.OCSAgent
        OCSAgent object which is running
    args: Namespace
        argparse namespace with site_config and agent specific arguments

    Attributes
    ----------
    agent: ocs.ocs_agent.OCSAgent
        OCSAgent object which is running
    log: txaio.tx.Logger
        txaio logger object created by agent
    prot: PysmurfScriptProtocol
        protocol used to call and monitor external pysmurf scripts
    protocol_lock: ocs.ocs_twisted.TimeoutLock
        lock to protect multiple pysmurf scripts from running simultaneously.
    """
    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log

        self.prot = None
        self.protocol_lock = TimeoutLock()

        self.current_session = None

        if args.monitor_id is not None:
            self.agent.subscribe_on_start(
                self._on_session_data,
                'observatory.{}.feeds.pysmurf_session_data'.format(args.monitor_id),
            )

    def _on_session_data(self, _data):
        data, feed = _data

        if self.current_session is not None:
            if data['id'] == os.environ.get("SMURFPUB_ID"):
                if data['type'] == 'session_data':
                    if isinstance(data['payload'], dict):
                        self.current_session.data.update(data['payload'])
                    else:
                        self.log.warn("Session data not passed as a dict!! Skipping...")

                elif data['type'] == 'session_log':
                    if isinstance(data['payload'], str):
                        self.current_session.add_message(data['payload'])

    @inlineCallbacks
    def _run_script(self, script, args, log, session):
        """
        Runs a pysmurf control script. Can only run from the reactor.

        Arguments
        ----------
        script: string
            path to the script you wish to run
        args: list, optional
            List of command line arguments to pass to the script.
            Defaults to [].
        log: string/bool, optional
            Determines if and how the process's stdout should be logged.
            You can pass the path to a logfile, True to use the agent's log,
            or False to not log at all.
        """

        with self.protocol_lock.acquire_timeout(0, job=script) as acquired:
            if not acquired:
                return False, "The requested script cannot be run because " \
                              "script {} is already running".format(self.protocol_lock.job)

            self.current_session = session
            try:
                # IO  is not really safe from the reactor thread, so we possibly
                # need to find another way to do this if people use it and it
                # causes problems...
                logger = None
                if isinstance(log, str):
                    self.log.info("Logging output to file {}".format(log))
                    log_file = yield threads.deferToThread(open, log, 'a')
                    logger = Logger(observer=FileLogObserver(log_file, log_formatter))
                elif log:
                    # If log==True, use agent's logger
                    logger = self.log

                self.prot = PysmurfScriptProtocol(script, log=logger)
                self.prot.deferred = Deferred()
                python_exec = sys.executable

                cmd = [python_exec, '-u', script] + list(map(str, args))

                self.log.info("{exec}, {cmd}", exec=python_exec, cmd=cmd)

                reactor.spawnProcess(self.prot, python_exec, cmd, env=os.environ)

                rc = yield self.prot.deferred

                return (rc == 0), "Script has finished with exit code {}".format(rc)

            finally:
                # Sleep to allow any remaining messages to be put into the
                # session var
                yield dsleep(1.0)
                self.current_session = None

    @inlineCallbacks
    def run_script(self, session, params=None):
        """run(params=None)

        Run task.
        Runs a pysmurf control script.

        Arguments
        ----------
        script: string
            path to the script you wish to run
        args: list, optional
            List of command line arguments to pass to the script.
            Defaults to [].
        log: string/bool, optional
            Determines if and how the process's stdout should be logged.
            You can pass the path to a logfile, True to use the agent's log,
            or False to not log at all.
        """

        ok, msg = yield self._run_script(
            params['script'],
            params.get('args', []),
            params.get('log', True),
            session
        )

        return ok, msg

    def abort_script(self, session, params=None):
        """
        Aborts the currently running script
        """
        self.prot.transport.signalProcess('KILL')
        return True, "Aborting process"

    @inlineCallbacks
    def tune_squids(self, session, params=None):
        """
        Task to run /config/scripts/pysmurf/tune_squids.py

        Arguments
        ---------
        args: list, optional
            List of command line arguments to pass to the script.
            Defaults to [].
        log: string/bool, optional
            Determines if and how the process's stdout should be logged.
            You can pass the path to a logfile, True to use the agent's log,
            or False to not log at all.
        """
        if params is None:
            params = {}

        ok, msg = yield self._run_script(
            '/config/scripts/pysmurf/tune_squids.py',
            params.get('args', []),
            params.get('log', True),
            session
        )

        return ok, msg


def make_parser(parser=None):
    """
    Builds argsparse parser, allowing sphinx to auto-document it.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Config')
    pgroup.add_argument('--plugin', action='store_true')
    pgroup.add_argument('--monitor-id', '-m', type=str,
                        help="Instance id for pysmurf-monitor corresponding to "
                             "this pysmurf instance.")

    return parser


if __name__ == '__main__':
    parser = site_config.add_arguments()

    parser = make_parser(parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'PysmurfController')

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args)

    agent.register_task('run', controller.run_script, blocking=False)
    agent.register_task('abort', controller.abort_script, blocking=False)
    agent.register_task('tune_squids', controller.tune_squids, blocking=False)

    runner.run(agent, auto_reconnect=True)
