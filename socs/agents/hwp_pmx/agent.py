import argparse
import time
from dataclasses import dataclass
from queue import Queue

import txaio
from twisted.internet import defer, reactor, threads

txaio.use_twisted()

from ocs import ocs_agent, site_config

import socs.agents.hwp_pmx.drivers.PMX_ethernet as pmx
from socs.agents.hwp_supervisor.agent import get_op_data


class Actions:
    class BaseAction:
        def __post_init__(self):
            self.deferred = defer.Deferred()
            self.log = txaio.make_logger()

    def process(self, *args, **kwargs):
        raise NotImplementedError

    @dataclass
    class SetOn(BaseAction):
        def process(self, module):
            self.log.info("Setting PMX on...")
            module.turn_on()

    @dataclass
    class SetOff(BaseAction):
        def process(self, module):
            self.log.info("Setting PMX off...")
            module.turn_off()

    @dataclass
    class UseExt(BaseAction):
        def process(self, module):
            self.log.info("Setting PMX Kikusui to PID control...")
            module.use_external_voltage()

    @dataclass
    class IgnExt(BaseAction):
        def process(self, module):
            self.log.info("Setting PMX Kikusui to direct control...")
            module.ign_external_voltage()

    @dataclass
    class ClearAlarm(BaseAction):
        def process(self, module):
            self.log.info("Clear PMX alarm...")
            module.clear_alarm()

    @dataclass
    class CancelShutdown(BaseAction):
        def process(self, module):
            self.log.info("Cancel shutdown...")

    @dataclass
    class CheckI(BaseAction):
        def process(self, module):
            msg, val = module.check_current()
            self.log.info(msg + "...")

    @dataclass
    class CheckV(BaseAction):
        def process(self, module):
            msg, val = module.check_voltage()
            self.log.info(msg + "...")

    @dataclass
    class SetI(BaseAction):
        curr: float

        def process(self, module):
            msg, val = module.set_current(self.curr)
            self.log.info(msg + "...")

    @dataclass
    class SetV(BaseAction):
        volt: float

        def process(self, module):
            msg, val = module.set_voltage(self.volt)
            self.log.info(msg + "...")

    @dataclass
    class CheckILim(BaseAction):
        def process(self, module):
            msg, val = module.check_current_limit()
            self.log.info(msg + "...")

    @dataclass
    class CheckVLim(BaseAction):
        def process(self, module):
            msg, val = module.check_voltage_limit()
            self.log.info(msg + "...")

    @dataclass
    class SetILim(BaseAction):
        curr: float

        def process(self, module):
            msg, val = module.set_current_limit(self.curr)
            self.log.info(msg + "...")

    @dataclass
    class SetVLim(BaseAction):
        volt: float

        def process(self, module):
            msg, val = module.set_voltage_limit(self.volt)
            self.log.info(msg + "...")


class HWPPMXAgent:
    """Agent for interfacing with a PMX Kikusui power supply
    to control the current and voltage that drive the rotation of the CHWP.

    Args:
        ip (str): IP address for the PMX Kikusui power supply
        port (str): Port for the PMX Kikusui power supply
        f_sample (float): sampling frequency (Hz)
        supervisor_id (str): Instance id of HWP supervisor
        no_data_timeout (float): Time (in seconds) to wait between receiving
            'no_data' actions from the supervisor and triggering a shutdown
    """

    def __init__(self, agent, ip, port, f_sample=1, supervisor_id=None,
                 no_data_timeout=15 * 60):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log

        self.ip = ip
        self.port = port
        self.action_queue = Queue()

        self.f_sample = f_sample

        self._initialized = False
        self.take_data = False
        self.prot = 0

        self.shutdown_mode = False
        self.supervisor_id = supervisor_id
        self.no_data_timeout = no_data_timeout

        agg_params = {'frame_length': 60}
        self.agent.register_feed(
            'hwppmx', record=True, agg_params=agg_params, buffer_time=1)

        self.agent.register_feed('rotation_action', record=True)

    @defer.inlineCallbacks
    def set_on(self, session, params):
        """set_on()
        **Task** - Turn on the PMX Kikusui.
        """
        action = Actions.SetOn(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set PMX Kikusui on'

    @defer.inlineCallbacks
    def set_off(self, session, params):
        """set_off()
        **Task** - Turn off the PMX Kikusui.
        """
        action = Actions.SetOff(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set PMX Kikusui off'

    @defer.inlineCallbacks
    def clear_alarm(self, session, params):
        """clear_alarm()
        **Task** - Clear alarm and exit protection mode.
        """
        action = Actions.ClearAlarm(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        self.prot = 0
        return True, 'Clear alarm'

    @defer.inlineCallbacks
    def use_ext(self, session, params):
        """use_ext()
        **Task** - Set the PMX Kikusui to use an external voltage control. Doing so
        enables PID control.
        """
        action = Actions.UseExt(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set PMX Kikusui to PID control'

    @defer.inlineCallbacks
    def ign_ext(self, session, params):
        """ign_ext()
        **Task** - Set the PMX Kiksui to ignore external voltage control. Doing so
        disables the PID and switches to direct control.
        """
        action = Actions.IgnExt(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set PMX Kikusui to direct control'

    @defer.inlineCallbacks
    def check_i(self, session, params):
        """check_i()
        **Task** - Set the current setting.
        """
        action = Actions.CheckI(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Check current is done'

    @defer.inlineCallbacks
    def check_v(self, session, params):
        """check_v()
        **Task** - Set the voltage setting.
        """
        action = Actions.CheckV(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Check voltage is done'

    @defer.inlineCallbacks
    @ocs_agent.param('curr', default=0, type=float)
    def set_i(self, session, params):
        """set_i(curr=0)
        **Task** - Set the current.

        Parameters:
            curr (float): set current
        """
        action = Actions.SetI(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set current is done'

    @defer.inlineCallbacks
    @ocs_agent.param('volt', default=0, type=float)
    def set_v(self, session, params):
        """set_v(volt=0)
        **Task** - Set the voltage.

        Parameters:
            volt (float): set voltage
        """
        action = Actions.SetV(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set voltage is done'

    @defer.inlineCallbacks
    def check_i_lim(self, session, params):
        """check_i_lim()
        **Task** - Check the current protection limit.
        """
        action = Actions.CheckILim(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Check current protection limit is done'

    @defer.inlineCallbacks
    def check_v_lim(self, session, params):
        """check_v_lim()
        **Task** - Check the voltage protection limit.
        """
        action = Actions.CheckVLim(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Check voltage protection limit is done'

    @defer.inlineCallbacks
    @ocs_agent.param('curr', default=1.3, type=float)
    def set_i_lim(self, session, params):
        """set_i_lim(curr=1.3)
        **Task** - Set the drive current limit.

        Parameters:
            curr (float): limit current
        """
        action = Actions.SetILim(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set voltage limit is done'

    @defer.inlineCallbacks
    @ocs_agent.param('volt', default=37., type=float)
    def set_v_lim(self, session, params):
        """set_v_lim(volt=37)
        **Task** - Set the drive voltage limit.

        Parameters:
            volt (float): limit voltage
        """
        action = Actions.SetVLim(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        return True, 'Set current limit is done'

    @defer.inlineCallbacks
    def initiate_shutdown(self, session, params):
        """ initiate_shutdown()
        **Task** - Initiate the shutdown of the agent.
        """
        self.log.warn("INITIATING SHUTDOWN")

        action = Actions.SetOff(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        self.shutdown_mode = True
        return True, "Initiated shutdown mode"

    @defer.inlineCallbacks
    def cancel_shutdown(self, session, params):
        """cancel_shutdown()
        **Task** - Cancels shutdown mode, allowing other tasks to update the power supply
        """
        action = Actions.CancelShutdown(**params)
        self.action_queue.put(action)
        session.data = yield action.deferred
        self.shutdown_mode = False
        return True, "Cancelled shutdown mode"

    def main(self, session, params):
        """main()

        **Process** - Start data acquisition.

        Notes:
            The most recent data collected is stored in session data in the
            structure::

                >>> response.session['data']
                {'curr': 0,
                 'volt': 0,
                 'prot': 0,
                 'last_updated': 1649085992.719602}

        """
        PMX = None

        threads.blockingCallFromThread(reactor, self._clear_queue)

        sleep_time = 1 / self.f_sample - 0.01
        last_daq = 0
        while session.status in ['starting', 'running']:
            if PMX is None:
                try:
                    PMX = pmx.PMX(ip=self.ip, port=self.port)
                except ConnectionRefusedError:
                    self.log.error(
                        "Could not connect to PMX. "
                        "Retrying after 30 sec..."
                    )
                    time.sleep(30)
                    continue

            now = time.time()
            if now - last_daq > sleep_time:
                self._get_and_publish_data(PMX, session)
                last_daq = now

            self._process_actions(PMX)
            time.sleep(0.1)

        PMX.close()
        return True, 'Stopped main'

    def _stop_main(self, session, params):
        """
        Stop acq process.
        """
        session.set_status('stopping')
        return True, 'Set main status to stopping'

    def _process_actions(self, PMX: pmx.PMX):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            if action.__class__.__name__ in ['SetOn', 'SetOff', 'SetI', 'SetV', 'UseExt', 'IgnExt']:
                if self.shutdown_mode:
                    self.log.warn("Shutdown mode is in effect")
                    action.deferred.errback(Exception("Action cancelled by shutdown mode"))
                    return
            try:
                self.log.info(f"Running action {action}")
                res = action.process(PMX)
                reactor.callFromThread(action.deferred.callback, res)
            except Exception as e:
                self.log.error(f"Error processing action: {action}")
                reactor.callFromThread(action.deferred.errback, e)

    def _clear_queue(self):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            action.deferred.errback(Exception("Action cancelled"))

    def _get_and_publish_data(self, PMX: pmx.PMX, session):
        now = time.time()
        data = {'timestamp': now,
                'block_name': 'hwppmx',
                'data': {}}

        try:
            msg, curr = PMX.meas_current()
            data['data']['current'] = curr

            msg, volt = PMX.meas_voltage()
            data['data']['voltage'] = volt

            msg, code = PMX.check_error()
            data['data']['err_code'] = code
            data['data']['err_msg'] = msg

            prot_code = PMX.check_prot()
            if prot_code != 0:
                self.prot = prot_code

            prot_msg = PMX.get_prot_msg(self.prot)
            data['data']['prot_code'] = self.prot
            data['data']['prot_msg'] = prot_msg

            msg, src = PMX.check_source()
            data['data']['source'] = src
            self.agent.publish_to_feed('hwppmx', data)
            session.data = {'curr': curr,
                            'volt': volt,
                            'prot': self.prot,
                            'prot_msg': prot_msg,
                            'source': src,
                            'last_updated': now}
        except BaseException:
            self.log.warn("Exception in getting data")
            return

    def monitor_supervisor(self, session, params):
        """monitor_supervisor()

        **Process** - This is a process that is constantly running to monitor the
        HWP supervisor and the recommended course of action
        course of action recommended by the HWP supervisor. If certain conditions
        are met, this will trigger a shutdown and force the power supply to
        power off.
        """

        last_ok_time = time.time()

        if self.supervisor_id is None:
            return False, "No supervisor ID set"

        while session.status in ['starting', 'running']:

            res = get_op_data(self.supervisor_id, 'monitor')
            if res['status'] != 'ok':
                action = 'no_data'
            else:
                action = res['data']['actions']['pmx']

            # If action is 'ok', update last_ok_time
            if action == 'ok':
                last_ok_time = time.time()

            # If action is 'no_data', check if last_ok_time, and potentially
            # trigger shutdown
            elif action == 'no_data':
                if (time.time() - last_ok_time) > self.no_data_timeout:
                    if not self.shutdown_mode:
                        self.agent.start('initiate_shutdown', params=None)

            # If action is 'shutdown', trigger shutdown
            elif action == 'stop':
                if not self.shutdown_mode:
                    self.agent.start('initiate_shutdown', params=None)

            data = {
                'data': {'rotation_action': action},
                'block_name': 'rotation_action',
                'timestamp': time.time()
            }

            self.agent.publish_to_feed('rotation_action', data)
            session.data = {
                'rotation_action': action,
                'time': time.time()
            }

            time.sleep(0.2)

        return True, 'Supervisor monitor has exited.'

    def _stop_monitor_supervisor(self, session, params):
        session.set_status('stopping')
        return True, "Stopping monitor shutdown."


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip', type=str,
                        help="ip address for kikusui PMX")
    pgroup.add_argument('--port', type=int,
                        help="port for kikusui PMX")
    pgroup.add_argument('--sampling-frequency', type=float, default=2.,
                        help="Sampling frequency for data acquisition")
    pgroup.add_argument('--supervisor-id', type=str,
                        help="Instance ID for HWP Supervisor agent")
    pgroup.add_argument('--no-data-timeout', type=float, default=15 * 60,
                        help="Time (sec) after which a 'no_data' action should "
                             "trigger a shutdown")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPPMXAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    kwargs = {
        'ip': args.ip, 'port': args.port, 'supervisor_id': args.supervisor_id,
        'no_data_timeout': args.no_data_timeout
    }
    if args.sampling_frequency is not None:
        kwargs['f_sample'] = args.sampling_frequency
    PMX = HWPPMXAgent(agent, **kwargs)

    agent.register_process('main', PMX.main, PMX._stop_main, startup=True)
    agent.register_process(
        'monitor_supervisor', PMX.monitor_supervisor, PMX._stop_monitor_supervisor,
        startup=True)
    agent.register_task('set_on', PMX.set_on, blocking=False)
    agent.register_task('set_off', PMX.set_off, blocking=False)
    agent.register_task('clear_alarm', PMX.clear_alarm, blocking=False)
    agent.register_task('check_i', PMX.check_i, blocking=False)
    agent.register_task('check_v', PMX.check_v, blocking=False)
    agent.register_task('set_i', PMX.set_i, blocking=False)
    agent.register_task('set_v', PMX.set_v, blocking=False)
    agent.register_task('check_i_lim', PMX.check_i_lim, blocking=False)
    agent.register_task('check_v_lim', PMX.check_v_lim, blocking=False)
    agent.register_task('set_i_lim', PMX.set_i_lim, blocking=False)
    agent.register_task('set_v_lim', PMX.set_v_lim, blocking=False)
    agent.register_task('use_ext', PMX.use_ext, blocking=False)
    agent.register_task('ign_ext', PMX.ign_ext, blocking=False)
    agent.register_task('initiate_shutdown', PMX.initiate_shutdown, blocking=False)
    agent.register_task('cancel_shutdown', PMX.cancel_shutdown, blocking=False)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
