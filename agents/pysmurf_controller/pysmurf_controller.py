from ocs import ocs_agent, site_config, client_t, ocs_twisted
from ocs.ocs_agent import log_formatter
import json
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, protocol
from twisted.internet.error import ProcessDone, ProcessTerminated
import sys
import datetime
from twisted.logger import Logger, formatEvent, FileLogObserver

from twisted.python.failure import Failure
import time
import os
import mysql.connector
import argparse

import importlib

from ocs.ocs_twisted import TimeoutLock
from twisted.enterprise import adbapi

from socs.util import get_db_connection, get_md5sum


class PysmurfScriptProtocol(protocol.ProcessProtocol):
    def __init__(self, path, log=None):
        self.path = path
        self.log = log
        self.end_status = None

    def connectionMade(self):
        print("Connection Made")
        self.transport.closeStdin()

    def outReceived(self, data):
        if self.log:
            self.log.info("{path}: {data}",
                          path=self.path.split('/')[-1],
                          data=data.strip().decode('utf-8'))

    def errReceived(self, data):
        self.log.error(data)

    def processExited(self, status):
        # if self.log is not None:
        #     self.log.info("Process ended: {reason}", reason=status)
        self.end_status = status


class PysmurfController:
    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = ocs_twisted.TimeoutLock()

        self.prot = None
        self.protocol_lock = TimeoutLock()

        self.plugin = args.plugin

    def _run_script(self, script, args, log):
        """
        Runs a pysmurf control script. Run primarily from tasks in worker threads.

        Args:

            script (string): path to the script you wish to run
            args (list, optional):
                List of command line arguments to pass to the script.
                Defaults to [].
            log (string/bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's log,
                or False to not log at all.
        """

        with self.protocol_lock.acquire_timeout(0, job=script) as acquired:
            if not acquired:
                return False, "Process {} is already running".format(self.protocol_lock.job)

            logger = None
            if isinstance(log, str):
                log_file = open(log, 'a')
                logger = Logger(observer=FileLogObserver(log_file, log_formatter))
            elif log:
                # If log==True, use agent's logger
                logger = self.log

            self.prot = PysmurfScriptProtocol(script, log=logger)
            python_exec = sys.executable

            cmd = [python_exec, '-u', script] + args
            self.log.info("{exec}, {cmd}", exec=python_exec, cmd=cmd)

            reactor.callFromThread(
                reactor.spawnProcess, self.prot, python_exec, cmd, env=os.environ
            )

            while self.prot.end_status is None:
                time.sleep(1)

            end_status = self.prot.end_status
            self.prot = None

            if isinstance(end_status.value, ProcessDone):
                return True, "Script has finished naturally"
            elif isinstance(end_status.value, ProcessTerminated):
                return False, "Script has been killed"

    def run_script(self, session, params=None):
        """
        Run task.
        Runs a pysmurf control script.

        Args:

            script (string): path to the script you wish to run
            args (list, optional):
                List of command line arguments to pass to the script.
                Defaults to [].
            log (string/bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's log,
                or False to not log at all.

        """
        ok, msg = self._run_script(params['script'],
                                   params.get('args', []),
                                   params.get('log', True))

        return ok, msg

    def abort_script(self, session, params=None):
        """
        Aborts the currently running script
        """
        self.prot.transport.signalProcess('KILL')
        return True, "Aborting process"

    def tune_squids(self, session, params=None):
        """
        Task to run tune_squids.py script

        Args:

            args (list, optional):
                List of command line arguments to pass to the script.
                Defaults to [].
            log (string/bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's log,
                or False to not log at all.
        """
        if params is None:
            params = {}

        ok, msg = self._run_script(
            '/config/scripts/pysmurf/tune_squids.py',
            params.get('args', []),
            params.get('log', True)
        )

        return ok, msg


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Config')
    pgroup.add_argument('--plugin', action='store_true')

    return parser


if __name__ == '__main__':
    parser = site_config.add_arguments()

    parser = make_parser(parser)

    args = parser.parse_args()

    site_config.reparse_args(args, 'PysmurfController')

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args)

    agent.register_task('run', controller.run_script)
    agent.register_task('abort', controller.abort_script)
    agent.register_task('tune_squids', controller.tune_squids)

    runner.run(agent, auto_reconnect=True)
