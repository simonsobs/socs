from dataclasses import asdict

import matplotlib
from autobahn.twisted.util import sleep as dsleep
from twisted.internet import protocol, reactor, threads
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.logger import FileLogObserver, Logger
from twisted.python.failure import Failure

matplotlib.use('Agg')
import argparse
import os
import sys
import time
from typing import Optional

import epics
import numpy as np
import sodetlib as sdl
from ocs import ocs_agent, site_config
from ocs.ocs_agent import log_formatter
from ocs.ocs_twisted import TimeoutLock
from sodetlib.det_config import DetConfig
from sodetlib.operations import bias_dets

from socs.agents.pysmurf_controller.smurf_subprocess_util import (
    QuantileData, RunCfg, RunResult, run_smurf_func)


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


def set_session_data(session, result: RunResult):
    """Sets session data based on a RunResult object"""
    if result.return_val is not None:
        if isinstance(result.return_val, dict):
            session.data = result.return_val
    session.data['result'] = asdict(result)


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
        slot (int):
            ATCA Slot of the smurf-card this agent is commanding.
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

        self.agent.register_feed('bias_step_results', record=True)
        self.agent.register_feed('noise_results', record=True)
        self.agent.register_feed('iv_results', record=True)
        self.agent.register_feed('bias_wave_results', record=True)
        self.agent.register_feed('state_results', record=True)

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

    def _get_smurf_control(self, session=None, load_tune=True, **kwargs):
        """
        Gets pysmurf and det-config instances for sodetlib functions.
        """
        cfg = DetConfig()
        cfg.load_config_files(slot=self.slot)
        S = cfg.get_smurf_control(**kwargs)
        if load_tune:
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

                >>> response.session['data']
                {
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

    @ocs_agent.param('poll_interval', type=float, default=10)
    @ocs_agent.param('test_mode', default=False, type=bool)
    def check_state(self, session, params=None):
        """check_state(poll_interval=10, test_mode=False)

        **Process** - Continuously checks the current state of the smurf. This
        will not modify the smurf state, so this task can be run in conjunction
        with other smurf operations. This will continuously poll smurf metadata
        and update the ``session.data`` object.

        Args
        -----
        poll_interval : float
            Time (sec) between updates.
        test_mode : bool, optional
            Run the Process loop only once. This is meant only for testing.
            Default is False.

        Notes
        -------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'channel_mask': Array of channels that are streaming data,
                'downsample_factor': downsample_factor,
                'agg_time': Buffer time per G3Frame (sec),
                'open_g3stream': True if data is currently streaming to G3,
                'pysmurf_action': Current pysmurf action,
                'pysmurf_action_timestamp': Current pysmurf-action timestamp,
                'stream_tag': stream-tag for the current g3 stream,
                'last_update':  Time that session-data was last updated,
                'stream_id': Stream-id of the controlled smurf instance,
                'num_active_channels': Number of channels outputting tones
            }
        """
        S, cfg = self._get_smurf_control(load_tune=False, no_dir=True)
        reg = sdl.Registers(S)

        kw = {'retry_on_fail': False}
        while session.status in ['starting', 'running']:
            try:

                num_active_channels = 0
                for band in range(8):
                    num_active_channels += len(S.which_on(band))

                d = dict(
                    channel_mask=S.get_channel_mask(**kw).tolist(),
                    downsample_factor=S.get_downsample_factor(**kw),
                    agg_time=reg.agg_time.get(**kw),
                    open_g3stream=reg.open_g3stream.get(**kw),
                    pysmurf_action=reg.pysmurf_action.get(**kw, as_string=True),
                    pysmurf_action_timestamp=reg.pysmurf_action_timestamp.get(**kw),
                    stream_tag=reg.stream_tag.get(**kw, as_string=True),
                    last_update=time.time(),
                    stream_id=cfg.stream_id,
                    num_active_channels=num_active_channels,
                )
                session.data.update(d)

                data = {
                    'timestamp': time.time(),
                    'block_name': 'state_results',
                    'data': {'open_g3stream': d['open_g3stream'],
                             'num_active_channels': d['num_active_channels']}
                }
                self.agent.publish_to_feed('state_results', data)
            except (RuntimeError, epics.ca.ChannelAccessGetFailure):
                self.log.warn("Could not connect to epics server! Waiting and "
                              "then trying again")

            time.sleep(params['poll_interval'])

            if params['test_mode']:
                break

        return True, "Finished checking state"

    def _stop_check_state(self, session, params):
        """Stopper for check state process"""
        session.set_status('stopping')

    def run_test_func(self, session, params):
        """run_test_func()

        **Task** - Task to test the subprocessing functionality without any
        smurf hardware.
        """
        cfg = RunCfg(
            func_name='test',
        )
        result = run_smurf_func(cfg)
        if not result.success:
            self.log.error("Subprocess errored out:\n{tb}", tb=result.traceback)

        if isinstance(result.return_val, dict):
            session.data = result.return_val
        else:
            session.data['data'] = result.return_val

        return result.success, 'finished'

    @ocs_agent.param("duration", default=None, type=float)
    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('load_tune', default=True, type=bool)
    @ocs_agent.param('stream_type', default='obs', choices=['obs', 'oper'])
    @ocs_agent.param('subtype', default=None)
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('test_mode', default=False, type=bool)
    def stream(self, session, params):
        """stream(duration=None, kwargs=None, load_tune=True, \
                  stream_type='obs', subtype=None, tag=None, test_mode=False)

        **Process** - Stream smurf data. If a duration is specified, stream
        will end after that amount of time. If unspecified, the stream will run
        until the stop function is called.

        Args
        -----
        duration : float, optional
            If set, determines how many seconds to stream data. By default,
            will leave stream open until stop function is called.
        kwargs : dict
            A dictionary containing additional keyword arguments to pass
            to sodetlib's ``stream_g3_on`` function
        load_tune : bool
            If true, will load a tune-file to the pysmurf object on
            instantiation.
        stream_type : string, optional
            Stream type. This can be either 'obs' or 'oper', and will be 'obs'
            by default. The tags attached to the stream will be
            ``<stream_type>,<subtype>,<tag>``.
        subtype : string, optional
            Operation subtype used tot tag the stream.
        tag : string, optional
            Tag (or comma-separated list of tags) to attach to the G3 stream.
            This has precedence over the `tag` key in the kwargs dict.
        test_mode : bool, optional
            Run the Process loop only once. This is meant only for testing.
            Default is False.

        Notes
        ------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'stream_id': Stream-id for the slot,
                'sid': Session-id for the streaming session,
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['stream_type']:
            params['kwargs']['tag'] = params['stream_type']
        if params['subtype'] is not None:
            params['kwargs']['subtype'] = params['subtype']
        if params['tag'] is not None:
            params['kwargs']['tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='stream') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session,
                                             load_tune=params['load_tune'])

            stop_time = None
            if params['duration'] is not None:
                stop_time = time.time() + params['duration']

            session.data['stream_id'] = cfg.stream_id
            session.data['sid'] = sdl.stream_g3_on(S, **params['kwargs'])
            while session.status in ['starting', 'running']:
                if stop_time is not None:
                    if time.time() > stop_time:
                        break
                time.sleep(1)

                if params['test_mode']:
                    break
            sdl.stream_g3_off(S)

        return True, 'Finished streaming data'

    def _stream_stop(self, session, params=None):
        session.set_status('stopping')
        return True, "Requesting to end stream"

    @ocs_agent.param('bands', default=None)
    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('run_in_main_procsess', default=False)
    def uxm_setup(self, session, params):
        """uxm_setup(bands=None, kwargs=None, run_in_main_process=False)

        **Task** - Runs first-time setup procedure for a UXM. This will run the
        following operations:

            1. Setup Amps (~1 min)
            2. Estimate attens if attens are not already set in the device cfg
               (~1 min / band)
            3. Estimate phase delay (~1 min / band)
            4. Setup tune (~7 min / band)
            5. Setup tracking param (~30s / band)
            6. Measure noise (~45s)

        See the `sodetlib setup docs
        <https://simons1.princeton.edu/docs/sodetlib/operations/setup.html#first-time-setup>`_
        for more information on the sodetlib setup procedure and allowed
        keyword arguments.

        Args
        -----
        bands : list, int
            Bands to set up. Defaults to all.
        kwargs : dict
            Dict containing additional keyword args to pass to the uxm_setup
            function.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        -------
        SODETLIB functions such as ``uxm_setup`` and any other functions called
        by ``uxm_setup`` will add relevant data to the ``session.data`` object
        to  a unique key. For example, if all is successful ``session.data``
        may look like::

            >> response.session['data']
            {
                'timestamps': [('setup_amps', 1651162263.0204525), ...],
                'setup_amps_summary': {
                   'success': True,
                   'amp_50k_Id': 15.0,
                   'amp_hemt_Id': 8.0,
                   'amp_50k_Vg': -0.52,
                   'amp_hemt_Vg': -0.829,
                },
                'setup_phase_delay': {
                    'bands': [0, 1, ...]
                    'band_delay_us': List of band delays
                },
                'noise': {
                   'band_medians': List of median white noise for each band
                }
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='uxm_setup') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            cfg = RunCfg(
                func_name='run_uxm_setup',
                kwargs={'bands': params['bands'], 'kwargs': params['kwargs']},
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.traceback is not None:
                self.log.error("Error occurred:\n{tb}", tb=result.traceback)
            return result.success, "Finished UXM Setup"

    @ocs_agent.param('bands', default=None)
    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def uxm_relock(self, session, params):
        """uxm_relock(bands=None, kwargs=None, run_in_main_process=False)

        **Task** - Relocks detectors to existing tune if setup has already been
        run. Runs the following operations:

            1. Setup Amps (~1 min)
            2. Relocks detectors, setup notches (if requested), and serial
               gradient descent / eta scan (~5 min / band)
            3. Tracking setup (~20s / band)
            4. Noise check (~45s)

        See the `sodetlib relock docs
        <https://simons1.princeton.edu/docs/sodetlib/operations/setup.html#relocking>`_
        for more information on the sodetlib relock procedure and allowed
        keyword arguments.

        Args
        -----
        bands : list, int
            Bands to set up. Defaults to all.
        kwargs : dict
            Dict containing additional keyword args to pass to the uxm_relock
            function.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        -------
        SODETLIB functions such as ``uxm_relock`` and any other functions called
        will add relevant data to the ``session.data`` object to  a unique key.
        For example, if all is successful ``session.data`` may look like::

            >> response.session['data']
            {
                'timestamps': [('setup_amps', 1651162263.0204525), ...],
                'setup_amps_summary': {
                   'success': True,
                   'amp_50k_Id': 15.0,
                   'amp_hemt_Id': 8.0,
                   'amp_50k_Vg': -0.52,
                   'amp_hemt_Vg': -0.829,
                },
                'noise': {
                   'band_medians': List of median white noise for each band
                }
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='uxm_relock') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            cfg = RunCfg(
                func_name='run_uxm_relock',
                kwargs={'bands': params['bands'], 'kwargs': params['kwargs']},
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.traceback is not None:
                self.log.error("Error occurred:\n{tb}", tb=result.traceback)

            return result.success, "Finished UXM Relock"

    @ocs_agent.param('duration', default=30., type=float)
    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def take_noise(self, session, params):
        """take_noise(duration=30., kwargs=None, tag=None, run_in_main_process=False)

        **Task** - Takes a short timestream and calculates noise statistics.
        Median white noise level for each band will be stored in the session
        data. See the `sodetlib noise docs
        <https://simons1.princeton.edu/docs/sodetlib/noise.html>`_ for more
        information on the noise function and possible keyword arguments.

        Args
        -----
        duration : float
            Duration of timestream to take for noise calculation.
        kwargs : dict
            Dict containing additional keyword args to pass to the take_noise
            function.
        tag : string, optional
            Tag (or comma-separated list of tags) to attach to the G3 stream.
            This has precedence over the `tag` key in the kwargs dict.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        -------
        Median white noise levels for each band will be stored in the
        session.data object, for example::

            >> response.session['data']
            {
                'noise': {
                   'band_medians': List of median white noise for each band
                }
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['tag'] is not None:
            params['kwargs']['g3_tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='take_noise') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            cfg = RunCfg(
                func_name='take_noise',
                args=[params['duration']],
                kwargs={'kwargs': params['kwargs']},
                run_in_main_process=params['run_in_main_process'],
            )

            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.success:
                block_data = {}
                for qd in result.return_val['quantiles'].values():
                    if isinstance(qd, dict):
                        qd = QuantileData(**qd)
                    block_data.update(qd.to_block_data())
                d = {
                    'timestamp': time.time(),
                    'block_name': 'noise_results',
                    'data': block_data
                }
                self.agent.publish_to_feed('noise_results', d)
            return result.success, "Finished taking noise"

    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def take_bgmap(self, session, params):
        """take_bgmap(kwargs=None, tag=None, run_in_main_process=False)

        **Task** - Takes a bias-group map. This will calculate the number of
        channels assigned to each bias group and put that into the session data
        object along with the filepath to the analyzed bias-step output. See
        the `bias steps docs page <https://simons1.princeton.edu/docs/sodetlib/operations/bias_steps.html>`_
        for more information on what additional keyword arguments can be
        passed.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to take_bgmap function.
        tag : Optional[str]
            String containing a tag or comma-separated list of tags to attach
            to the g3 stream.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        ------
        The filepath of the BiasStepAnalysis object and the number of channels
        assigned to each bias group will be written to the session.data
        object::

            >> response.session['data']
            {
                'nchans_per_bg': [123, 183, 0, 87, ...],
                'filepath': /path/to/bias_step_file/on/smurf_server.npy,
            }

        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['tag'] is not None:
            params['kwargs']['g3_tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='take_bgmap') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            kwargs = {
                'show_plots': False,
            }
            kwargs.update(params['kwargs'])
            cfg = RunCfg(
                func_name='take_bgmap',
                kwargs={'kwargs': kwargs},
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            return result.success, "Finished taking bgmap"

    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def take_iv(self, session, params):
        """take_iv(kwargs=None, tag=None, run_in_main_process=False)

        **Task** - Takes an IV. This will add the normal resistance array and
        channel info to the session data object along with the analyzed IV
        filepath. See the `sodetlib IV docs page
        <https://simons1.princeton.edu/docs/sodetlib/operations/iv.html>`_
        for more information on what additional keyword arguments can be passed
        in.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to the ``take_iv`` function.
        tag : Optional[str]
            String containing a tag or comma-separated list of tags to attach
            to the g3 stream.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        ------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'filepath': Filepath of saved IVAnalysis object
                'quantiles': {
                    'Rn': Rn quantiles
                    'p_sat': electrical power at 90% Rn quantiles
                }
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['tag'] is not None:
            params['kwargs']['g3_tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='take_iv') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."
            cfg = RunCfg(
                func_name='take_iv',
                kwargs={'iv_kwargs': params['kwargs']},
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.success:
                block_data = {}
                for qd in result.return_val['quantiles'].values():
                    if isinstance(qd, dict):
                        qd = QuantileData(**qd)
                    block_data.update(qd.to_block_data())
                d = {
                    'timestamp': time.time(),
                    'block_name': 'iv_results',
                    'data': block_data
                }
                self.agent.publish_to_feed('iv_results', d)
            return result.success, "Finished taking IV"

    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('rfrac_range', default=(0.2, 0.9))
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def take_bias_steps(self, session, params):
        """take_bias_steps(kwargs=None, rfrac_range=(0.2, 0.9), tag=None, run_in_main_process=False)

        **Task** - Takes bias_steps and saves the output filepath to the
        session data object. See the `sodetlib bias step docs page
        <https://simons1.princeton.edu/docs/sodetlib/operations/bias_steps.html>`_
        for more information on bias steps and what kwargs can be passed in.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to ``take_bais_steps`` function.
        rfrac_range : tuple
            Range of valid rfracs to check against when determining the number
            of good detectors.
        tag : Optional[str]
            String containing a tag or comma-separated list of tags to attach
            to the g3 stream.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        ------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'filepath': Filepath of saved BiasStepAnalysis object
                'biased_total': Total number of detectors biased into rfrac_range
                'biased_per_bg': List containing number of biased detectors on each bias line
                'quantiles': {
                    'Rtes': Rtes quantiles,
                    'Rfrac': Rfrac quantiles,
                    'Si': Si quantiles,
                }
            }
        """

        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['tag'] is not None:
            params['kwargs']['g3_tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='bias_steps') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            cfg = RunCfg(
                func_name='take_bias_steps',
                kwargs={
                    'kwargs': params['kwargs'], 'rfrac_range': params['rfrac_range'],
                },
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.success:  # Publish quantile results
                block_data = {
                    f'biased_bg{bg}': v
                    for bg, v in enumerate(result.return_val['biased_per_bg'])
                }
                block_data['biased_total'] = result.return_val['biased_total']
                for qd in result.return_val['quantiles'].values():
                    if isinstance(qd, dict):
                        qd = QuantileData(**qd)
                    block_data.update(qd.to_block_data())
                data = {
                    'timestamp': time.time(),
                    'block_name': 'bias_steps_results',
                    'data': block_data
                }
                self.agent.publish_to_feed('bias_step_results', data)

            return result.success, "Finished taking bias steps"

    @ocs_agent.param('bgs', default=None)
    @ocs_agent.param('kwargs', default=None)
    @ocs_agent.param('tag', default=None)
    @ocs_agent.param('run_in_main_process', default=False, type=bool)
    def take_bias_waves(self, session, params):
        """take_bias_waves(kwargs=None, rfrac_range=(0.2, 0.9), tag=None, run_in_main_process=False)

        **Task** - Takes bias_wave and saves the output filepath to the
        session data object.

        Args
        ----
        kwargs : dict
            Additional kwargs to pass to ``take_bias_wave`` function.
        rfrac_range : tuple
            Range of valid rfracs to check against when determining the number
            of good detectors.
        tag : Optional[str]
            String containing a tag or comma-separated list of tags to attach
            to the g3 stream.
        run_in_main_process : bool
            If true, run smurf-function in main process. Mainly for the purpose
            of testing without the reactor running.

        Notes
        ------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'filepath': Filepath of saved BiasWaveAnalysis object
                'biased_total': Total number of detectors biased into rfrac_range
                'biased_per_bg': List containing number of biased detectors on each bias line
                'quantiles': {
                    'Rtes': Rtes quantiles,
                    'Rfrac': Rfrac quantiles,
                    'Si': Si quantiles,
                }
            }
        """

        if params['kwargs'] is None:
            params['kwargs'] = {}

        if params['tag'] is not None:
            params['kwargs']['g3_tag'] = params['tag']

        with self.lock.acquire_timeout(0, job='bias_wave') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            cfg = RunCfg(
                func_name='take_bias_waves',
                kwargs={
                    'kwargs': params['kwargs'], 'rfrac_range': params['rfrac_range'],
                },
                run_in_main_process=params['run_in_main_process'],
            )
            result = run_smurf_func(cfg)
            set_session_data(session, result)
            if result.success:  # Publish quantile results
                block_data = {
                    f'biased_bg{bg}': v
                    for bg, v in enumerate(result.return_val['biased_per_bg'])
                }
                block_data['biased_total'] = result.return_val['biased_total']
                for qd in result.return_val['quantiles'].values():
                    block_data.update(QuantileData(**qd).to_block_data())
                data = {
                    'timestamp': time.time(),
                    'block_name': 'bias_wave_results',
                    'data': block_data
                }
                self.agent.publish_to_feed('bias_wave_results', data)

            return result.success, "Finished taking bias steps"

    @ocs_agent.param('bgs', default=None)
    @ocs_agent.param('kwargs', default=None)
    def overbias_tes(self, session, params):
        """overbias_tes(bgs=None, kwargs=None)

        **Task** - Overbiases detectors using S.overbias_tes_all.

        Args
        -------
        bgs : List[int]
            List of bias groups to overbias. If this is set to None, it will
            use all active bgs.
        kwargs : dict
            Additional kwargs to pass to the ``overbias_tes_all`` function.
        """
        kw = {'bias_groups': params['bgs']}
        if params['kwargs'] is not None:
            kw.update(params['kwargs'])

        with self.lock.acquire_timeout(0, job='overbias_tes') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session)
            sdl.overbias_dets(S, cfg, **kw)

        return True, "Finished Overbiasing TES"

    @ocs_agent.param('bias')
    @ocs_agent.param('bgs', default=None)
    def set_biases(self, session, params):
        """set_biases(bias, bgs=None)

        **Task** - Task used to set TES biases.

        Args
        -----
        bias: int, float, list
            Biases to set. If a float is passed, this will be used for all
            specified bgs. If a list of floats is passed, it must be the same
            size of the list of bgs.
        bgs: int, list, optional
            Bias group (bg), or list of bgs to set. If None, will set all bgs.
        """
        if params['bgs'] is None:
            bgs = np.arange(12)
        else:
            bgs = np.atleast_1d(params['bgs'])

        if isinstance(params['bias'], (int, float)):
            biases = [params['bias'] for _ in bgs]
        else:
            if len(params['bias']) != len(bgs):
                return False, "Number of biases must match number of bgs"
            biases = params['bias']

        with self.lock.acquire_timeout(0, job='set_biases') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, _ = self._get_smurf_control(session=session)

            for bg, bias in zip(bgs, biases):
                S.set_tes_bias_bipolar(bg, bias)

            return True, f"Finished setting biases to {params['bias']}"

    @ocs_agent.param('bgs', default=None)
    def zero_biases(self, session, params):
        """zero_biases(bgs=None)

        **Task** - Zeros TES biases for specified bias groups.

        Args
        -----
        bgs: int, list, optional
            bg, or list of bgs to zero. If None, will zero all bgs.
        """
        params['bias'] = 0
        self.agent.start('set_biases', params)
        self.agent.wait('set_biases')
        return True, 'Finished zeroing biases'

    @ocs_agent.param('rfrac', default=(0.3, 0.6))
    @ocs_agent.param('kwargs', default=None)
    def bias_dets(self, session, params):
        """bias_dets(rfrac=(0.3, 0.6), kwargs=None)

        **Task** - Biases detectors to a target Rfrac value or range. This
        function uses IV results to determine voltages for each bias-group. If
        rfrac is set to be a value, the bias voltage will be set such that the
        median rfrac across all channels is as close as possible to the set
        value. If a range is specified, the voltage will be chosen to maximize
        the number of channels in that range.

        See the sodetlib docs page for `biasing dets into transition
        <https://simons1.princeton.edu/docs/sodetlib/operations/iv.html#biasing-detectors-into-transition>`_
        for more information on the functions and additional keyword args that
        can be passed in.

        Args
        -------
        rfrac : float, tuple
            Target rfrac range to aim for. If this is a float, bias voltages
            will be chosen to get the median rfrac of each bias group as close
            as possible to that value. If
        kwargs : dict
            Additional kwargs to pass to the ``bias_dets`` function.

        Notes
        ------
        The following data will be written to the session.data object::

            >> response.session['data']
            {
                'biases': List of voltage bias values for each bias-group
            }
        """
        if params['kwargs'] is None:
            params['kwargs'] = {}

        with self.lock.acquire_timeout(0, job='bias_steps') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session)
            if isinstance(params['rfrac'], (int, float)):
                biases = bias_dets.bias_to_rfrac(
                    S, cfg, rfrac=params['rfrac'], **params['kwargs']
                )
            else:
                biases = bias_dets.bias_to_rfrac_range(
                    S, cfg, rfrac_range=params['rfrac'], **params['kwargs']
                )

            session.data['biases'] = biases.tolist()

            return True, "Finished biasing detectors"

    @ocs_agent.param('disable_amps', default=True, type=bool)
    @ocs_agent.param('disable_tones', default=True, type=bool)
    def all_off(self, session, params):
        """all_off(disable_amps=True, disable_tones=True)

        **Task** - Turns off tones, flux-ramp voltage and amplifier biases

        Args
        -------
        disable_amps: bool
            If True, will disable amplifier biases
        disable_tones: bool
            If True, will turn off RF tones and flux-ramp signal
        """
        with self.lock.acquire_timeout(0, job='all_off') as acquired:
            if not acquired:
                return False, f"Operation failed: {self.lock.job} is running."

            S, cfg = self._get_smurf_control(session=session)
            if params['disable_tones']:
                S.all_off()
            if params['disable_amps']:
                S.C.write_ps_en(0)

            return True, "Everything off"


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
    pgroup.add_argument('--poll-interval', type=float,
                        help="Time between check-state polls")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='PysmurfController',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args)

    agent.register_task('run', controller.run, blocking=False)
    agent.register_task('abort', controller.abort, blocking=False)

    startup_pars = {}
    if args.poll_interval is not None:
        startup_pars['poll_interval'] = args.poll_interval
    agent.register_process(
        'check_state', controller.check_state, controller._stop_check_state,
        startup=startup_pars
    )
    agent.register_process(
        'stream', controller.stream, controller._stream_stop
    )
    agent.register_task('uxm_setup', controller.uxm_setup)
    agent.register_task('uxm_relock', controller.uxm_relock)
    agent.register_task('take_bgmap', controller.take_bgmap)
    agent.register_task('bias_dets', controller.bias_dets)
    agent.register_task('take_iv', controller.take_iv)
    agent.register_task('take_bias_steps', controller.take_bias_steps)
    agent.register_task('take_bias_waves', controller.take_bias_waves)
    agent.register_task('overbias_tes', controller.overbias_tes)
    agent.register_task('take_noise', controller.take_noise)
    agent.register_task('bias_dets', controller.bias_dets)
    agent.register_task('all_off', controller.all_off)
    agent.register_task('set_biases', controller.set_biases)
    agent.register_task('zero_biases', controller.zero_biases)
    agent.register_task('run_test_func', controller.run_test_func)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
