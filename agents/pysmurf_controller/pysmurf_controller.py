from twisted.internet import reactor, protocol, threads
from twisted.python.failure import Failure
from twisted.internet.error import ProcessDone, ProcessTerminated
from twisted.internet.defer import inlineCallbacks, Deferred
from autobahn.twisted.util import sleep as dsleep
from twisted.logger import Logger, FileLogObserver

import matplotlib
matplotlib.use('Agg')
import sodetlib as sdl
from sodetlib.operations import (
    uxm_setup, uxm_relock, bias_steps, iv, tracking, bias_dets
)
from sodetlib.det_config import DetConfig
import numpy as np

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

    Args:
        agent (ocs.ocs_agent.OCSAgent):
            OCSAgent object which is running
        args (Namespace):
            argparse namespace with site_config and agent specific arguments

    Attributes:
        agent (ocs.ocs_agent.OCSAgent):
            OCSAgent object which is running
        log (txaio.tx.Logger):
            txaio logger object created by agent
        prot (PysmurfScriptProtocol):
            protocol used to call and monitor external pysmurf scripts
        lock (ocs.ocs_twisted.TimeoutLock):
            lock to protect multiple pysmurf scripts from running simultaneously.
    """
    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log

        self.prot = None
        self.lock = TimeoutLock()

        self.current_session = None

        self.slot = args.slot
        if self.slot is None:
            self.slot = os.environ['SLOT']

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

    def _get_smurf_control(self, session=None):
        """
        Gets pysmurf and detconfig instances for sodetlib functions.
        """
        cfg = DetConfig()
        cfg.load_config_files(slot=self.slot)
        S = cfg.get_smurf_control()
        S.load_tune(cfg.dev.exp['tunefile'])
        S._ocs_session = session
        return S, cfg


    @inlineCallbacks
    def _run_script(self, script, args, log, session):
        """
        Runs a pysmurf control script. Can only run from the reactor.

        Args:
            script (string):
                path to the script you wish to run
            args (list, optional):
                List of command line arguments to pass to the script.
                Defaults to [].
            log (string or bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's log,
                or False to not log at all.
        """

        with self.lock.acquire_timeout(0, job=script) as acquired:
            if not acquired:
                return False, "The requested script cannot be run because " \
                              "script {} is already running".format(self.lock.job)

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
    def run(self, session, params=None):
        """run(script, args=[], log=True)

        **Task** - Runs a pysmurf control script.

        Parameters:
            script (string):
                Path of the pysmurf script to run.
            args (list, optional):
                List of command line arguments to pass to the script.  Defaults
                to [].
            log (string/bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's
                log, or False to not log at all.

        Notes:
            Data and logs may be passed from the pysmurf control script to the
            session object by publishing it via the Pysmurf Publisher using the
            message types ``session_data`` and ``session_logs`` respectively.

            For example, below is a simple script which starts the data stream
            and returns the datfile path and the list of active channels to the
            session::

                active_channels = S.which_on(0)
                datafile = S.stream_data_on()
                S.pub.publish({
                    'datafile': datafile, 'active_channels': active_channels
                }, msgtype='session_data')

            This would result in the following session.data object::

                >>> {
                    'datafile': '/data/smurf_data/20200316/1584401673/outputs/1584402020.dat',
                    'active_channels': [0,1,2,3,4]
                }

        """
        ok, msg = yield self._run_script(
            params['script'],
            params.get('args', []),
            params.get('log', True),
            session
        )

        return ok, msg

    def abort(self, session, params=None):
        """abort()

        **Task** - Aborts the actively running script.

        """
        self.prot.transport.signalProcess('KILL')
        return True, "Aborting process"

    @ocs_agent.param("duration", default=None, type=float)
    def stream(self, session, params):
        """stream(duration=30)

        **Process** - Process to stream smurf data. If a duration is specified,
        stream will end after that amount of time. If unspecified, the stream
        will run until the stop function is called.

        Args
        -----
        duration : float, optional
            If set, determines how many seconds to stream data. By default,
            will leave stream open until stop function is called.
        """
        with self.lock.acquire_timeout(0, job='stream') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session)

            stop_time = None
            if params['duration'] is not None:
                stop_time = time.time() + params['duration']

            session.data['sid'] = sdl.stream_g3_on(S)
            session.set_status('running')
            while session.status in ['starting', 'running']:
                if stop_time is not None:
                    if time.time() > stop_time:
                        break
                time.sleep(1)
            sdl.stream_g3_off(S)

        return True, 'Finished streaming data'

    def _stream_stop(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting to end stream"

    @ocs_agent.param('bands', default=None)
    @ocs_agent.param('kwargs', default=None)
    def uxm_setup(self, session, params):
        """
        **Task** - Task to run first-time setup procedure for a UXM. This
        will run the following operations:

            1. Setup Amps
            2. Estimate attens
            3. Estimate phase delay
            4. Setup tune
            5. setup tracking params
            6. Measure noise

        Args
        -----
        bands : list, int
            Bands to set up.
        kwargs : dict
            Dict containing additional keyword args to pass to the uxm_setup
            function.
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='uxm_setup') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session)
            session.set_status('running')
            self.log.info("Starting UXM setup")
            success, summary = uxm_setup.uxm_setup(
                S, cfg, bands=params['bands'], **params['kwargs']
            )
            return success, "Finished UXM-setup procedure"

    @ocs_agent.param('bands', default=None)
    @ocs_agent.param('kwargs', default=None)
    def uxm_relock(self, session, params):
        """
        **Task** - Task to relock detectors to existing tune if setup has
        already been run. Runs the following operations:

            1. Setup Amps
            2. Relocks detectors, setup notches (if requested), and serial
               gradient descent / eta scan
            3. Tracking setup
            4. Noise check

        Args
        -----
        bands : list, int
            Bands to set up.
        kwargs : dict
            Dict containing additional keyword args to pass to the uxm_relock
            function.
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='uxm_relock') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            session.set_status('running')
            S, cfg = self._get_smurf_control(session=session)
            success, summary = uxm_relock.uxm_relock(
                S, cfg, bands=params['bands'], **params['kwargs']
            )
            return success, "Finished UXM Relock"

    @ocs_agent.param('duration', default=30., type=float)
    @ocs_agent.param('kwargs', default=None)
    def take_noise(self, session, params):
        """
        **Task** - Task to take a short timestream and calculate noise
        statistics. Puts band medians into the session data.

        Args
        -----
        duration : float
            Bands to set up.
        kwargs : dict
            Dict containing additional keyword args to pass to the uxm_relock
            function.
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='take_noise') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            session.set_status('running')
            S, cfg = self._get_smurf_control(session=session)
            sdl.noise.take_noise(S, cfg, params['duration'], **params['kwargs'])
            return True, "Finished taking noise"

    @ocs_agent.param('kwargs', default=None)
    def take_bgmap(self, session, params):
        """
        **Task** - Takes a bias-group map.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to take_bgmap function.
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='take_bgmap') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            session.set_status('running')
            S, cfg = self._get_smurf_control(session=session)
            bsa = bias_steps.take_bgmap(S, cfg, **params['kwargs'])
            nchans_per_bg = [0 for _ in range(13)]
            for bg in range(12):
                nchans_per_bg[bg] = int(np.sum(bsa.bgmap == bg))
            nchans_per_bg[-1] = int(np.sum(bsa.bgmap == -1))

            session.data = {
                'nchans_per_bg': nchans_per_bg,
                'filepath': bsa.filepath,
            }
            return True, "Finished taking bgmap"

    @ocs_agent.param('kwargs', default=None)
    def take_iv(self, session, params):
        """take_iv(kwargs=None)

        Takes an IV.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to take_bgmap function.
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='uxm_setup') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            session.set_status('starting')
            S, cfg = self._get_smurf_control()
            iva = iv.take_iv(S, cfg, **params['kwargs'])
            session.data = {
                'bands': iva.bands.tolist(),
                'channels': iva.channels.tolist(),
                'bgmap': iva.bgmap.tolist(),
                'R_n': iva.R_n.tolist(),
                'filepath': iva.filepath,
            }
            return True, "Finished taking IV"

    @ocs_agent.param('kwargs', default=None)
    def take_bias_steps(self, session, params):
        """take_iv(kwargs=None)

        Takes bias_steps

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to take_bgmap function.
        """

        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='bias_steps') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            session.set_status('starting')
            S, cfg = self._get_smurf_control()
            bsa = bias_steps.take_bias_steps(
                S, cfg, **params['kwargs']
            )
            session.data = {
                'filepath': bsa.filepath
            }

            return True, "Finished taking bias steps"

def make_parser(parser=None):
    """
    Builds argsparse parser, allowing sphinx to auto-document it.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--monitor-id', '-m', type=str,
                        help="Instance id for pysmurf-monitor corresponding to "
                             "this pysmurf instance.")
    pgroup.add_argument('--slot', type=int,
                        help="Smurf slot that this agent will be controlling")
    return parser

if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='PysmurfController', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args)

    agent.register_task('run', controller.run, blocking=False)
    agent.register_task('abort', controller.abort, blocking=False)
    agent.register_process(
        'stream', controller.stream, controller._stream_stop
    )
    agent.register_task('uxm_setup', controller.uxm_setup)
    agent.register_task('uxm_relock', controller.uxm_relock)
    agent.register_task('take_bgmap', controller.take_bgmap)
    agent.register_task('take_iv', controller.take_iv)
    agent.register_task('take_bias_steps', controller.take_bias_steps)
    agent.register_task('take_noise', controller.take_noise)

    runner.run(agent, auto_reconnect=True)
