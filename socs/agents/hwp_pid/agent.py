import argparse
import queue
import time

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet import defer, reactor, threads

txaio.use_twisted()


from dataclasses import dataclass

import socs.agents.hwp_pid.drivers.pid_controller as pd


def parse_action_result(res):
    """
    Parses the result of an action to ensure it is a dictionary so it can be
    stored in session.data
    """
    if res is None:
        return {}
    elif isinstance(res, dict):
        return res
    else:
        return {'result': res}


def get_pid_state(pid: pd.PID):
    state_func = {'current_freq': pid.get_freq,
                  'target_freq': pid.get_target,
                  'direction': pid.get_direction}

    return_dict = {'healthy': True}
    for name, func in state_func.items():
        resp = func()
        if resp.msg_type == 'error':
            return_dict['healthy'] = False
        else:
            return_dict[name] = resp.measure
    return return_dict


class Actions:
    @dataclass
    class BaseAction:
        def __post_init__(self):
            self.deferred = defer.Deferred()
            self.log = txaio.make_logger()

    @dataclass
    class TuneStop(BaseAction):
        def process(self, pid: pd.PID):
            pid.tune_stop()

    @dataclass
    class TuneFreq(BaseAction):
        def process(self, pid: pd.PID):
            pid.tune_freq()

    @dataclass
    class DeclareFreq(BaseAction):
        freq: float

        def process(self, pid: pd.PID):
            pid.declare_freq(self.freq)
            return {"declared_freq": self.freq}

    @dataclass
    class SetPID(BaseAction):
        p: float
        i: int
        d: float

        def process(self, pid: pd.PID):
            pid.set_pid([self.p, self.i, self.d])

    @dataclass
    class SetDirection(BaseAction):
        direction: str

        def process(self, pid: pd.PID):
            pid.set_direction(self.direction)

    @dataclass
    class SetScale(BaseAction):
        slope: float
        offset: float

        def process(self, pid: pd.PID):
            pid.set_scale(self.slope, self.offset)

    @dataclass
    class GetState(BaseAction):
        def process(self, pid: pd.PID):
            pid_state = get_pid_state(pid)
            if pid_state['healthy']:
                return pid_state
            else:
                print('Error getting state')
                raise ValueError


class HWPPIDAgent:
    """Agent to PID control the rotation speed of the CHWP

    Args:
        ip (str): IP address for the PID controller
        port (str): Port for the PID controller
        verbosity (str): Verbosity of PID controller output

    """

    def __init__(self, agent, ip, port, verbosity):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self._initialized = False
        self.take_data = False
        self.ip = ip
        self.port = port
        self._verbosity = verbosity > 0
        self.action_queue = queue.Queue()

        agg_params = {"frame_length": 60}
        self.agent.register_feed("hwppid", record=True, agg_params=agg_params)

    def _get_data_and_publish(self, pid: pd.PID, session: ocs_agent.OpSession):
        data = {"timestamp": time.time(), "block_name": "HWPPID", "data": {}}

        pid_state = get_pid_state(pid)
        if pid_state['healthy']:
            session.degraded = False
        else:
            print('Warning: state monitor degraded')
            session.degraded = True

        data['data'].update(pid_state)
        session.data.update(pid_state)
        session.data['last_updated'] = time.time()
        self.agent.publish_to_feed("hwppid", data)

    def _process_actions(self, pid):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            try:
                self.log.info(f"Running action {action}")
                res = action.process(pid)
                threads.blockingCallFromThread(
                    reactor, action.deferred.callback, res
                )
            except Exception as e:
                self.log.error(f"Error processing action: {action}")
                threads.blockingCallFromThread(
                    reactor, action.deferred.errback, e
                )

    def _clear_queue(self):
        while not self.action_queue.empty():
            action = self.action_queue.get()
            action.deferred.errback(Exception("Action cancelled"))

    def main(self, session, params):
        """main()

        **Process** - Main Process for PID agent. Periodically queries PID
            controller for data, and executes requested actions.

        Notes:
            The most recent data collected is stored in the session data in the
            structure::

                >>> response.session['data']
                {'current_freq': 0,
                 'target_freq': 0,
                 'direction': 1,
                 'last_updated': 1649085992.719602}
        """
        pid = pd.PID(ip=self.ip, port=self.port, verb=self._verbosity)
        self.log.info("Connected to PID controller")

        self._clear_queue()

        sample_period = 5.0
        last_sample = 0.0
        session.set_status("running")
        while session.status in ["starting", "running"]:
            now = time.time()
            if now - last_sample > sample_period:
                self._get_data_and_publish(pid, session)
                last_sample = now

            self._process_actions(pid)
            time.sleep(0.2)

        return True, "Exited main process"

    def _main_stop(self, session, params):
        """Stop main process"""
        session.set_status("stopping")
        return True, "Set main status to stopping"

    @defer.inlineCallbacks
    def tune_stop(self, session, params):
        """tune_stop()

        **Task** - Reverse the drive direction of the PID controller and
        optimize the PID parameters for deceleration.

        """
        action = Actions.TuneStop(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    def tune_freq(self, session, params):
        """tune_freq()

        **Task** - Tune the PID controller setpoint to the rotation frequency
        and optimize the PID parameters for rotation.

        """
        action = Actions.TuneFreq(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    @ocs_agent.param("freq", default=0.0, check=lambda x: 0.0 <= x <= 3.0)
    def declare_freq(self, session, params):
        """declare_freq(freq=0)

        **Task** - Store the entered frequency as the PID setpoint when
        ``tune_freq()`` is next called.

        Parameters:
            freq (float): Desired HWP rotation frequency

        Notes:
            Session data is structured as follows::

                >>> response.session['data']
                {'declared_freq': 2.0}
        """
        action = Actions.DeclareFreq(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    @ocs_agent.param("p", default=0.2, type=float, check=lambda x: 0.0 < x <= 8.0)
    @ocs_agent.param("i", default=63, type=int, check=lambda x: 0 <= x <= 200)
    @ocs_agent.param("d", default=0.0, type=float, check=lambda x: 0.0 <= x < 10.0)
    def set_pid(self, session, params):
        """set_pid(p=0.2, i=63, d=0.)

        **Task** - Set the PID parameters. Note these changes are for the
        current session only and will change whenever the agent container is
        reloaded.

        Parameters:
            p (float): Proportional PID value
            i (int): Integral PID value
            d (float): Derivative PID value
        """
        action = Actions.SetPID(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    @ocs_agent.param("direction", type=str, default="0", choices=["0", "1"])
    def set_direction(self, session, params):
        """set_direction(direction='0')

        **Task** - Set the HWP rotation direction.

        Parameters:
            direction (str): '0' for forward and '1' for reverse.

        """
        action = Actions.SetDirection(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    @ocs_agent.param("slope", default=1.0, type=float, check=lambda x: -10.0 < x < 10.0)
    @ocs_agent.param(
        "offset", default=0.1, type=float, check=lambda x: -10.0 < x < 10.0
    )
    def set_scale(self, session, params):
        """set_scale(slope=1, offset=0.1)

        **Task** - Set the PID's internal conversion from input voltage to
        rotation frequency.

        Parameters:
            slope (float): Slope of the "rotation frequency vs input voltage"
                relationship
            offset (float): y-intercept of the "rotation frequency vs input
                voltage" relationship

        """
        action = Actions.SetScale(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"

    @defer.inlineCallbacks
    def get_state(self, session, params):
        """get_state()

        **Task** - Polls hardware for the current the PID state.

        Notes:
            Session data for this operation is as follows::

                >>> response.session['data']
                {'current_freq': 0,
                 'target_freq': 0,
                 'direction': 1}
        """
        action = Actions.GetState(**params)
        self.action_queue.put(action)
        res = yield action.deferred
        session.data = parse_action_result(res)
        return True, f"Completed: {str(action)}"


def make_parser(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically build documentation
    baised on this function
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--ip")
    pgroup.add_argument("--port")
    pgroup.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="PID Controller verbosity level.",
    )
    pgroup.add_argument("--mode")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class="HWPPIDAgent", parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    if args.mode is not None:
        agent.log.warn("--mode agrument is deprecated.")

    hwppid_agent = HWPPIDAgent(
        agent, ip=args.ip, port=args.port, verbosity=args.verbose
    )
    agent.register_process(
        "main", hwppid_agent.main, hwppid_agent._main_stop, startup=True
    )
    agent.register_task("tune_stop", hwppid_agent.tune_stop, blocking=False)
    agent.register_task("tune_freq", hwppid_agent.tune_freq, blocking=False)
    agent.register_task("declare_freq", hwppid_agent.declare_freq, blocking=False)
    agent.register_task("set_pid", hwppid_agent.set_pid, blocking=False)
    agent.register_task("set_direction", hwppid_agent.set_direction, blocking=False)
    agent.register_task("set_scale", hwppid_agent.set_scale, blocking=False)
    agent.register_task("get_state", hwppid_agent.get_state, blocking=False)
    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
