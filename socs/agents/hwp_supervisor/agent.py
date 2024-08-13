import argparse
import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Literal, Optional

import numpy as np
import ocs
import txaio
from ocs import client_http, ocs_agent, site_config
from ocs.client_http import ControlClientError
from ocs.ocs_client import OCSClient, OCSReply
from ocs.ocs_twisted import Pacemaker

client_cache = {}


def get_op_data(agent_id, op_name, log=None, test_mode=False):
    """
    Process data from an agent operation, and formats it for the ``monitor``
    operation session data.

    Parameters
    --------------
    agent_id : str
        Instance ID of the agent
    op_name : str
        Operation from which to grab session data
    log : logger, optional
        Log object
    test_mode : bool
        If True, this will run in test mode, and not try to connect to the
        specified agent.

    Returns
    -----------
    Returns a dictionary with the following fields:

    agent_id: str
        Instance id for the agent being queried
    op_name : str
        Operation name being queried
    timestamp : float
        Time the operation status was queried
    data : dict
        Session data of the operation. This will be ``None`` if we can't connect
        to the operation.
    status : str
        Connection status of the operation. This can be the following:

        - ``no_agent_provided``: if the passed agent_id is None
        - ``test_mode``: if ``test_mode=True``, this will be the status and no
          operation will be queried.
        - ``op_not_found``: This means the operation could not be found, likely
          meaning the agent isn't running
        - ``no_active_session``: This means the operation specified exists but
           was never run.
        - ``ok``: Operation and session.data exist
    """
    if log is None:
        log = txaio.make_logger()  # pylint: disable=E1101

    data = {
        'agent_id': agent_id,
        'op_name': op_name,
        'timestamp': time.time(),
        'data': None
    }
    if agent_id is None:
        data['status'] = 'no_agent_provided'
        return data

    if test_mode:
        data['status'] = 'test_mode'
        return data

    args = []
    if 'SITE_HTTP' in os.environ:
        args += [f"--site-http={os.environ['SITE_HTTP']}"]

    if agent_id in client_cache:
        client = client_cache[agent_id]
    else:
        client = site_config.get_control_client(agent_id, args=args)
        client_cache[agent_id] = client

    try:
        _, _, session = OCSReply(*client.request('status', op_name))
    except client_http.ControlClientError as e:
        log.warn('Error getting status: {e}', e=e)
        data['status'] = 'op_not_found'
        return data

    if not session:
        data['status'] = 'no_active_session'
        return data

    data['data'] = session['data']
    data['status'] = 'ok'
    return data


@dataclass
class HWPClients:
    encoder: Optional[OCSClient] = None
    pmx: Optional[OCSClient] = None
    pid: Optional[OCSClient] = None
    ups: Optional[OCSClient] = None
    lakeshore: Optional[OCSClient] = None
    gripper_iboot: Optional[OCSClient] = None
    driver_iboot: Optional[OCSClient] = None
    pcu: Optional[OCSClient] = None


@dataclass
class IBootState:
    instance_id: str
    outlets: List[int]
    agent_type: Literal['iboot, synaccess']
    outlet_state: Dict[int, Optional[int]] = None
    op_data: Optional[Dict] = None

    def __post_init__(self):
        self.outlet_state = {o: None for o in self.outlets}

    def update(self):
        op = get_op_data(self.instance_id, 'acq', test_mode=False)
        self.op_data = op
        if op['status'] != 'ok':
            self.outlet_state = {o: None for o in self.outlets}
            return

        if self.agent_type == 'iboot':
            self.outlet_labels = {o: f'outletStatus_{o}' for o in self.outlets}
            self.outlet_state = {
                outlet: op['data'][label]['status']
                for outlet, label in self.outlet_labels.items()
            }
        elif self.agent_type == 'synaccess':
            self.outlet_labels = {o: str(o - 1) for o in self.outlets}
            self.outlet_state = {
                outlet: op['data']['fields'][label]['status']
                for outlet, label in self.outlet_labels.items()
            }
        else:
            raise ValueError(
                f"Invalid agent_type: {self.agent_type}. "
                "Must be in ['iboot', 'synaccess']"
            )


@dataclass
class ACUState:
    """
    Class containing ACU state information.

    Args
    ------
    instance_id : str
        Instance ID of ACU agent
    min_el : float
        Minimum elevation allowed before restricting spin-up [deg]
    max_el : float
        Maximum elevation allowed before restricting spin-up [deg]
    max_time_since_update : float
        Maximum time since last update before restricting spin-up[sec]

    Attributes
    ------------
    el_current_position : float
        Current el position [deg]
    el_commanded_position : float
        Commanded el position [deg]
    el_current_velocity : float
        Current el velocity [deg/s]
    last_updated : float
        Time of last update [sec]
    """
    instance_id: str
    min_el: float
    max_el: float
    max_time_since_update: float

    el_current_position: Optional[float] = None
    el_commanded_position: Optional[float] = None
    el_current_velocity: Optional[float] = None
    last_updated: Optional[float] = None

    def update(self):
        op = get_op_data(self.instance_id, 'monitor')
        if op['status'] != 'ok':
            return

        d = op['data'].get("StatusDetailed")
        if d is None:
            return

        self.el_current_position = d['Elevation current position']
        self.el_commanded_position = d['Elevation commanded position']
        self.el_current_velocity = d['Elevation current velocity']
        t = d.get('timestamp_agent')
        if t is None:
            t = time.time()
        self.last_updated = t


@dataclass
class HWPState:
    temp: Optional[float] = None
    temp_status: Optional[str] = None
    temp_thresh: Optional[float] = None
    temp_field: Optional[str] = None

    ups_output_source: Optional[str] = None
    ups_estimated_minutes_remaining: Optional[float] = None
    ups_estimated_charge_remaining: Optional[float] = None
    ups_battery_voltage: Optional[float] = None
    ups_battery_current: Optional[float] = None
    ups_minutes_remaining_thresh: Optional[float] = None
    ups_connected: Optional[bool] = None
    ups_last_connection_attempt: Optional[bool] = None

    pid_current_freq: Optional[float] = None
    pid_target_freq: Optional[float] = None
    pid_direction: Optional[str] = None
    pid_last_updated: Optional[float] = None

    pmx_current: Optional[float] = None
    pmx_voltage: Optional[float] = None
    pmx_source: Optional[str] = None
    pmx_last_updated: Optional[float] = None

    enc_freq: Optional[float] = None
    last_quad: Optional[float] = None
    last_quad_time: Optional[float] = None

    gripper_iboot: Optional[IBootState] = None
    driver_iboot: Optional[IBootState] = None

    acu: Optional[ACUState] = None

    @classmethod
    def from_args(cls, args: argparse.Namespace):
        log = txaio.make_logger()  # pylint: disable=E1101
        self = cls(
            temp_field=args.ybco_temp_field,
            temp_thresh=args.ybco_temp_thresh,
            ups_minutes_remaining_thresh=args.ups_minutes_remaining_thresh,
        )

        if args.gripper_iboot_id is not None:
            self.gripper_iboot = IBootState(args.gripper_iboot_id, args.gripper_iboot_outlets,
                                            args.gripper_power_agent_type)
            log.info("Gripper Ibootbar id set: {id}", id=args.gripper_iboot_id)
        else:
            log.warn("Gripper Ibootbar id not set")

        if args.driver_iboot_id is not None:
            self.driver_iboot = IBootState(args.driver_iboot_id, args.driver_iboot_outlets,
                                           args.driver_power_agent_type)
            log.info("Driver Ibootbar id set: {id}", id=args.driver_iboot_id)
        else:
            log.warn("Driver Ibootbar id not set")

        if args.acu_instance_id is not None:
            self.acu = ACUState(
                instance_id=args.acu_instance_id,
                min_el=args.acu_min_el,
                max_el=args.acu_max_el,
                max_time_since_update=args.acu_max_time_since_update
            )
            log.info("ACU state checking enabled: instance_id={id}",
                     id=self.acu.instance_id)
        else:
            log.info("ACU state checking disabled.")

        return self

    def _update_from_keymap(self, op, keymap):
        if op['status'] != 'ok':
            for k in keymap:
                setattr(self, k, None)
            return

        for k, v in keymap.items():
            setattr(self, k, op['data'].get(v))

    def update_enc_state(self, op):
        """
        Updates state values from the encoder acq operation results.

        Args
        -----
        op : dict
            Dict containing the operations (from get_op_data) from the encoder
            ``acq`` process
        """
        self._update_from_keymap(op, {
            'enc_freq': 'approx_hwp_freq',
            'encoder_last_updated': 'encoder_last_updated',
            'last_quad': 'last_quad',
            'last_quad_time': 'last_quad_time',
        })

    def update_temp_state(self, op):
        """
        Updates state values from the Lakeshore acq operation results.

        Args
        -----
        op : dict
            Dict containing the operations (from get_op_data) from the lakeshore
            ``acq`` process
        """
        if op['status'] != 'ok':
            self.temp = None
            self.temp_status = 'no_data'
            return

        fields = op['data']['fields']
        if self.temp_field not in fields:
            self.temp = None
            self.temp_status = 'no_data'
            return

        self.temp = fields[self.temp_field]['T']

        if self.temp_thresh is not None:
            if self.temp > self.temp_thresh:
                self.temp_status = 'over'
            else:
                self.temp_status = 'ok'
        else:
            self.temp_status = 'ok'

    def update_pmx_state(self, op):
        """
        Updates state values from the pmx main operation results.

        Args
        -----
        op : dict
            Dict containing the operations (from get_op_data) from the pmx
            ``main`` process
        """
        keymap = {'pmx_current': 'curr', 'pmx_voltage': 'volt',
                  'pmx_source': 'source', 'pmx_last_updated': 'last_updated'}
        self._update_from_keymap(op, keymap)

    def update_pid_state(self, op):
        """
        Updates state values from the pid main operation results.

        Args
        -----
        op : dict
            Dict containing the operations (from get_op_data) from the pid
            ``main`` process
        """
        self._update_from_keymap(op, {
            'pid_current_freq': 'current_freq',
            'pid_target_freq': 'target_freq',
            'pid_direction': 'direction',
            'pid_last_updated': 'last_updated'
        })

    def update_ups_state(self, op):
        """
        Updates state values from the UPS acq operation results.

        Args
        -----
        op : dict
            Dict containing the operations (from get_op_data) from the UPS
            ``acq`` process
        """
        ups_keymap = {
            'ups_output_source': ('upsOutputSource', 'description'),
            'ups_estimated_minutes_remaining': ('upsEstimatedMinutesRemaining', 'status'),
            'ups_estimated_charge_remaining': ('upsEstimatedChargeRemaining', 'status'),
            'ups_battery_voltage': ('upsBatteryVoltage', 'status'),
            'ups_battery_current': ('upsBatteryCurrent', 'status'),
        }

        if op['status'] != 'ok':
            for k in ups_keymap:
                setattr(self, k, None)
            return

        # get oid
        data = op['data']
        for k in data:
            if k.startswith('upsOutputSource'):
                ups_oid = k.split('_')[1]
                break
        else:
            raise ValueError('Could not find upsOutputSource OID')

        for k, f in ups_keymap.items():
            setattr(self, k, data[f'{f[0]}_{ups_oid}'][f[1]])

        self.ups_last_connection_attempt = data['ups_connection']['last_attempt']
        self.ups_connected = data['ups_connection']['connected']

    @property
    def pmx_action(self):
        """
        PMX action to take based on the current state of the HWP. This can be
        ``stop``, ``ok``, or ``no_data``.
        """
        # First check if either ups or temp are beyond a threshold
        if self.temp is not None and self.temp_thresh is not None:
            if self.temp > self.temp_thresh:
                return 'stop'

        min_remaining = self.ups_estimated_minutes_remaining
        min_remaining_thresh = self.ups_minutes_remaining_thresh
        if min_remaining is not None and min_remaining_thresh is not None and \
                self.ups_output_source is not None:
            if min_remaining < min_remaining_thresh and \
                    self.ups_output_source != 'normal':
                return 'stop'

        # If either ybco_temp or ups state is None, return no_data
        if self.temp is None and (self.temp_thresh is not None):
            return 'no_data'

        if min_remaining is None and (min_remaining_thresh is not None):
            return 'no_data'

        return 'ok'

    @property
    def gripper_action(self):
        """
        Gripper action to take based on the current state of the HWP. This can be
        ``stop``, ``ok``, or ``no_data``.
        """
        pmx_action = self.pmx_action
        if pmx_action == 'ok':
            return 'ok'
        if pmx_action == 'no_data':
            return 'no_data'

        if self.pid_current_freq is None:
            return 'no_data'
        elif self.pid_current_freq > 0.01:
            return 'ok'
        else:  # Only grip if the hwp_freq is smaller than 0.01
            return 'stop'


class ControlStateInfo:
    def __init__(self, state):
        """
        Class that holds the control state dataclass, and relevant metadata
        such as start time and last_update time.

        Args
        ------
        state : ControlState
            ControlState object
        """
        self.state = state
        self.last_update_time = 0
        self.start_time = time.time()
        self.state_type = state.__class__.__name__

    def encode(self):
        d = {
            'state_type': self.state_type,
            'start_time': self.start_time,
            'last_update_time': self.last_update_time,
        }
        d.update(asdict(self.state))
        return d


class ControlState:
    """Namespace for HWP control state definitions"""
    @dataclass
    class Idle:
        """Does nothing"""

    @dataclass
    class PIDToFreq:
        """
        Configures PID and PMX agents to PID to a target frequency.

        Attributes
        -----------
        target_freq : float
            Target frequency to PID to
        direction : str
            Direction to set the PID. Should either be '1' or '0'.
        freq_tol : float
            Tolerance between the target frequency and the current frequency
            to consider the target frequency reached.
        freq_tol_duration : float
            Duration in seconds that the frequency must be within the tolerance
        """
        target_freq: float
        direction: str
        freq_tol: float
        freq_tol_duration: float

    @dataclass
    class CheckInitialRotation:
        """
        In this state, will check if the HWP has started rotating. If it has not
        started rotating in ``check_wait_time`` seconds, it will briefly turn on the PCU
        to initiate rotation, before transitioning to the WaitForTargetFreq state.
        """
        target_freq: float
        freq_tol: float
        freq_tol_duration: float
        direction: str
        check_wait_time: float = 15.0
        start_time: float = field(default_factory=time.time)

    @dataclass
    class WaitForTargetFreq:
        """
        Wait until HWP reaches its target frequency before transitioning to
        the Done state.

        Attributes
        -----------
        target_freq : float
            Target frequency to PID to
        freq_tol : float
            Tolerance between the target frequency and the current frequency
            to consider the target frequency reached.
        freq_tol_duration : float
            Duration in seconds that the frequency must be within the tolerance
        freq_within_thresh_start : float
            Time that the frequency entered the tolerance range
        start_time : float
            Time that the state was entered
        """
        target_freq: float
        freq_tol: float
        freq_tol_duration: float
        freq_within_tol_start: Optional[float] = None
        direction: str = ''
        _pcu_enabled: bool = field(init=False, default=False)

    @dataclass
    class ConstVolt:
        """
        Configure PMX agent to output a constant voltage.

        Attributes
        -----------
        voltage : float
            Voltage to set the PMX to
        start_time : float
            Time that the state was entered
        """
        voltage: float
        direction: str

    @dataclass
    class Done:
        """
        Signals the last state has completed

        Attributes
        -----------
        success : bool
            Whether the last state was completed successfully
        msg : str
            Optional message to include with the Done state
        start_time : float
            Time that the state was entered
        """
        success: bool
        msg: str = None

    @dataclass
    class Error:
        """
        Signals the last state update threw an error

        Attributes
        -----------
        traceback : str
            Traceback of the error
        start_time : float
            Time that the state was entered
        """
        traceback: str
        start_time: float = field(default_factory=time.time)

    @dataclass
    class Brake:
        """
        Configure the PID and PMX agents to actively brake the HWP
        """
        freq_tol: float
        freq_tol_duration: float
        brake_voltage: float

    @dataclass
    class WaitForBrake:
        """
        Waits until the HWP has slowed before shutting off PMX

        min_freq : float
            Frequency (Hz) below which the PMX should be shut off.
        """
        min_freq: float
        prev_freq: float = None

    @dataclass
    class PmxOff:
        """
        Turns off the PMX

        Attributes
        -----------
        start_time : float
            Time that the state was entered
        """
        success: bool = True

    @dataclass
    class Abort:
        """Abort current action"""
        pass

    @dataclass
    class EnableDriverBoard:
        """
        Enables driver boards for encoder LEDs

        Attributes
        -----------
        driver_power_agent_type : Literal["iboot", "synaccess"]
            Type of agent used for controlling the driver power. Must be
            "iboot" or "synaccess".
        outlets : List[int]
            Outlets required for enabling driver board
        cycle_twice : bool
            If true, will wait, and then power cycle again
        cycle_wait_time : float
            Time [sec] before repeating the power cycle
        """
        driver_power_agent_type: Literal['iboot, synaccess']
        outlets: List[int]
        cycle_twice: bool = False
        cycle_wait_time: float = 60 * 5

        def __post_init__(self):
            if self.driver_power_agent_type not in ['iboot', 'synaccess']:
                raise ValueError(
                    f"Invalid driver_power_agent_type: {self.driver_power_agent_type}. "
                    "Must be in ['iboot', 'synaccess']"
                )
            self.cycled = False
            self.cycle_timestamp = None

    @dataclass
    class DisableDriverBoard:
        """
        Disables driver board for encoder LEDs

        Attributes
        -----------
        driver_power_agent_type: Literal['iboot, synaccess']
            Type of agent used for controlling the driver power
        outlets: List[int]
            Outlets required for enabling driver board
        """
        driver_power_agent_type: Literal['iboot, synaccess']
        outlets: List[int]

        def __post_init__(self):
            if self.driver_power_agent_type not in ['iboot', 'synaccess']:
                raise ValueError(
                    f"Invalid driver_power_agent_type: {self.driver_power_agent_type}. "
                    "Must be in ['iboot', 'synaccess']"
                )

    completed_states = (Done, Error, Abort, Idle)


class ControlAction:
    """
    This is a class to contain data regarding a single HWP control action.
    This groups together states that are part of a single action, and whether
    the action is completed and successful.
    """
    _cur_action_id: int = 0
    _id_lock = threading.Lock()

    def __init__(self, state):
        with ControlAction._id_lock:
            self.action_id = ControlAction._cur_action_id
            ControlAction._cur_action_id += 1

        self.completed = False
        self.success = False
        self.state_history = []
        self.log = txaio.make_logger()  # pylint: disable=E1101
        self.set_state(state)

    def set_state(self, state):
        """
        Sets state for the current action. If this is a `completed_state`,
        will mark as complete.
        """
        self.cur_state_info = ControlStateInfo(state)
        self.state_history.append(self.cur_state_info)
        self.log.info(f"Setting state: {state}")
        if isinstance(state, ControlState.completed_states):
            self.completed = True
        if isinstance(state, ControlState.Done):
            self.success = state.success

    def encode(self):
        """Encodes this as a dict"""
        return dict(
            action_id=self.action_id,
            completed=self.completed,
            success=self.success,
            cur_state=self.cur_state_info.encode(),
            state_history=[s.encode() for s in self.state_history],
        )

    def sleep_until_complete(self, session=None, dt=1):
        """
        Sleeps until the action is complete.

        Args
        -----
        session: OpSession, optional
            If specified, this will set `session.data['action']` to the encoded
            action on each iteration to keep session data up to date
        dt: float, optional
            Time to sleep between iterations.
        """
        while True:
            if session is not None:
                session.data.update({'action': self.encode()})
            if self.completed:
                return
            time.sleep(dt)


class ControlStateMachine:
    def __init__(self):
        self.action: ControlAction = ControlAction(ControlState.Idle())
        self.action_history: List[ControlAction] = []
        self.max_action_history_count = 100
        self.log = txaio.make_logger()  # pylint: disable=E1101
        self.lock = threading.Lock()

    def run_and_validate(self, op, kwargs=None, timeout=30, log=None):
        """
        Runs an OCS Operation, and validates that it was successful.

        Args
        -------
        op : OCS MatchedOp
            Operation to run. This must be a MatchedOp, or a method of an
            OCSClient
        kwargs : dict, optional
            Kwargs to pass to the operation
        timeout : float, optional
            Timeout for the wait command. This defaults to
            ``default_wait_timeout`` which is 10 seconds. If this is set to
            None, will wait indefinitely.
        """
        if kwargs is None:
            kwargs = {}
        if log is None:
            log = self.log

        status, msg, session = op.start(**kwargs)
        log.info("Starting op: name={name}, kwargs={kw}",
                 name=session.get('op_name'), kw=kwargs)

        if status == ocs.ERROR:
            raise ControlClientError("op-start returned Error:\n  msg: " + msg)

        if status == ocs.TIMEOUT:
            raise ControlClientError("op-start timed out")

        status, msg, session = op.wait(timeout=timeout)

        if status == ocs.ERROR:
            raise ControlClientError("op-wait returned Error:\n  msg: " + msg)

        if status == ocs.TIMEOUT:
            raise ControlClientError("op-wait timed out")

        log.info("Completed op: name={name}, success={success}, kwargs={kw}",
                 name=session.get('op_name'), success=session.get('success'),
                 kw=kwargs)

        return session

    def update(self, clients, hwp_state: HWPState):
        """Run the next series of actions for the current state"""
        try:
            self.lock.acquire()
            state = self.action.cur_state_info.state
            self.action.cur_state_info.last_update_time = time.time()

            def query_pid_state():
                data = self.run_and_validate(clients.pid.get_state)['data']
                self.log.info("pid state: {data}", data=data)
                return data

            def check_acu_ok_for_spinup():
                acu = hwp_state.acu
                if acu is not None:
                    if acu.last_updated is None:
                        raise RuntimeError(f"No ACU data has been received from instance-id {acu.instance_id}")
                    tdiff = time.time() - acu.last_updated
                    if tdiff > acu.max_time_since_update:
                        raise RuntimeError(f"ACU state has not been updated in {tdiff} sec")
                    if not (acu.min_el <= acu.el_current_position <= acu.max_el):
                        raise RuntimeError(f"ACU elevation is {acu.el_current_pos} deg, "
                                           f"outside of allowed range ({acu.min_el}, {acu.max_el})")
                    if not (acu.min_el <= acu.el_commanded_position <= acu.max_el):
                        raise RuntimeError(f"ACU commanded elevation is {acu.el_commanded_position} deg, "
                                           f"outside of allowed range ({acu.min_el}, {acu.max_el})")

            if isinstance(state, ControlState.PIDToFreq):
                check_acu_ok_for_spinup()
                self.run_and_validate(clients.pid.set_direction,
                                      kwargs={'direction': state.direction})
                self.run_and_validate(clients.pid.declare_freq,
                                      kwargs={'freq': state.target_freq})
                self.run_and_validate(clients.pmx.use_ext)
                self.run_and_validate(clients.pmx.set_on)
                self.run_and_validate(clients.pid.tune_freq, timeout=60)
                self.run_and_validate(
                    clients.pcu.send_command,
                    kwargs={'command': 'off'}, timeout=None,
                )
                self.action.set_state(ControlState.CheckInitialRotation(
                    target_freq=state.target_freq,
                    freq_tol=state.freq_tol,
                    freq_tol_duration=state.freq_tol_duration,
                    direction=state.direction,
                ))

            if isinstance(state, ControlState.CheckInitialRotation):
                fhwp = hwp_state.enc_freq
                if fhwp >= 0.2:
                    self.action.set_state(ControlState.WaitForTargetFreq(
                        target_freq=state.target_freq,
                        freq_tol=state.freq_tol,
                        freq_tol_duration=state.freq_tol_duration,
                        direction=state.direction,
                    ))
                    return

                if time.time() - state.start_time < state.check_wait_time:
                    return

                if int(state.direction) == 1:  # Reverse
                    self.run_and_validate(
                        clients.pcu.send_command,
                        kwargs={'command': 'on_1'}, timeout=None
                    )
                else:
                    self.run_and_validate(
                        clients.pcu.send_command,
                        kwargs={'command': 'on_2'}, timeout=None
                    )
                time.sleep(3)
                self.run_and_validate(
                    clients.pcu.send_command,
                    kwargs={'command': 'off'}, timeout=None
                )
                self.action.set_state(ControlState.WaitForTargetFreq(
                    target_freq=state.target_freq,
                    freq_tol=state.freq_tol,
                    freq_tol_duration=state.freq_tol_duration,
                    direction=state.direction,
                ))

            elif isinstance(state, ControlState.WaitForTargetFreq):
                # Check if we are close enough to the target frequency.
                # This will make sure we remain within the frequency threshold for
                # ``self.freq_tol_duration`` seconds before switching to DONE
                f = hwp_state.pid_current_freq

                # Enable pcu if spinning up faster than 1.5 Hz
                if state.target_freq > 1.5 and f > 1.0 and not state._pcu_enabled:
                    self.log.info("Enabling PCU")
                    if int(state.direction) == 1:  # Reverse
                        self.run_and_validate(
                            clients.pcu.send_command,
                            kwargs={'command': 'on_1'}, timeout=None
                        )
                    else:
                        self.run_and_validate(
                            clients.pcu.send_command,
                            kwargs={'command': 'on_2'}, timeout=None
                        )
                    state._pcu_enabled = True

                if f is None:
                    state.freq_within_tol_start = None
                    return

                if np.abs(f - state.target_freq) > state.freq_tol:
                    state.freq_within_tol_start = None
                    return

                # If within tolerance for freq_tol_duration, switch to Done
                if state.freq_within_tol_start is None:
                    state.freq_within_tol_start = time.time()

                time_within_tol = time.time() - state.freq_within_tol_start
                if time_within_tol > state.freq_tol_duration:
                    self.action.set_state(ControlState.Done(success=True))

            elif isinstance(state, ControlState.ConstVolt):
                if state.voltage > 0:
                    check_acu_ok_for_spinup()
                self.run_and_validate(clients.pmx.set_on)
                self.run_and_validate(clients.pid.set_direction,
                                      kwargs={'direction': state.direction})
                self.run_and_validate(clients.pmx.ign_ext)
                self.run_and_validate(clients.pmx.set_v,
                                      kwargs={'volt': state.voltage})
                self.action.set_state(ControlState.Done(success=True))

            elif isinstance(state, ControlState.PmxOff):
                self.run_and_validate(clients.pmx.set_off)
                self.run_and_validate(clients.pid.declare_freq,
                                      kwargs={'freq': 0})
                self.run_and_validate(clients.pid.tune_freq)
                self.run_and_validate(
                    clients.pcu.send_command,
                    kwargs={'command': 'stop'}, timeout=None
                )
                self.action.set_state(ControlState.Done(success=state.success))

            elif isinstance(state, ControlState.Brake):
                self.run_and_validate(
                    clients.pcu.send_command,
                    kwargs={'command': 'off'}, timeout=None
                )

                # Flip PID direciton and tune stop
                pid_dir = int(query_pid_state()['direction'])
                new_d = '0' if (pid_dir == 1) else '1'
                self.run_and_validate(clients.pid.set_direction,
                                      kwargs=dict(direction=new_d))
                self.run_and_validate(clients.pid.tune_stop)

                self.run_and_validate(clients.pmx.ign_ext)
                self.run_and_validate(clients.pmx.set_v, kwargs={'volt': state.brake_voltage})
                self.run_and_validate(clients.pmx.set_on)

                time.sleep(10)
                self.action.set_state(ControlState.WaitForBrake(
                    min_freq=0.5,
                    prev_freq=hwp_state.enc_freq,
                ))

            elif isinstance(state, ControlState.WaitForBrake):
                f0 = query_pid_state()['current_freq']
                time.sleep(5)
                f1 = query_pid_state()['current_freq']
                if f0 < 0.5 or (f1 > f0):
                    self.log.info("Turning off PMX and putting PCU in stop mode")
                    self.run_and_validate(clients.pmx.set_off)
                    self.run_and_validate(
                        clients.pcu.send_command,
                        kwargs={'command': 'stop'}, timeout=None
                    )
                    self.action.set_state(ControlState.WaitForTargetFreq(
                        target_freq=0,
                        freq_tol=0.05,
                        freq_tol_duration=30,
                    ))
                    return

            elif isinstance(state, ControlState.EnableDriverBoard):
                def set_outlet_state(outlet: int, outlet_state: bool):
                    if state.driver_power_agent_type == 'iboot':
                        kw = {'outlet': outlet, 'state': 'on' if outlet_state else 'off'}
                    else:
                        kw = {'outlet': outlet, 'on': outlet_state}
                    self.run_and_validate(clients.driver_iboot.set_outlet, kwargs=kw)

                if not state.cycled:
                    for outlet in state.outlets:
                        set_outlet_state(outlet, True)
                    state.cycled = True
                    state.cycle_timestamp = time.time()
                    if not state.cycle_twice:
                        self.action.set_state(ControlState.Done(success=True))
                        return

                # Needs to be re-cycled, after wait time
                if time.time() - state.cycle_timestamp < state.cycle_wait_time:
                    return

                for outlet in state.outlets:
                    set_outlet_state(outlet, False)
                time.sleep(5)
                for outlet in state.outlets:
                    set_outlet_state(outlet, True)
                self.action.set_state(ControlState.Done(success=True))
                return

            elif isinstance(state, ControlState.DisableDriverBoard):
                def set_outlet_state(outlet: int, outlet_state: bool):
                    if state.driver_power_agent_type == 'iboot':
                        kw = {'outlet': outlet, 'state': 'on' if outlet_state else 'off'}
                    else:
                        kw = {'outlet': outlet, 'on': outlet_state}
                    self.run_and_validate(clients.driver_iboot.set_outlet, kwargs=kw)

                for outlet in state.outlets:
                    set_outlet_state(outlet, False)
                self.action.set_state(ControlState.Done(success=True))
                return

        except Exception:
            tb = traceback.format_exc()
            self.log.error("Error updating state:\n{tb}", tb=tb)
            self.action.set_state(ControlState.Error(traceback=tb))
        finally:
            self.lock.release()

    def request_new_action(self, state):
        """
        Requests that a new action is started with a given state.
        If an action is already in progress, it will be aborted.
        """
        with self.lock:
            if not self.action.completed:
                self.action.set_state(ControlState.Abort())
            if len(self.action_history) > self.max_action_history_count:
                self.action_history.pop(0)
            self.action = ControlAction(state)
            self.action_history.append(self.action)
            return self.action


class HWPSupervisor:
    """
    The HWPSupervisor agent is responsible for monitoring HWP and related
    components, and high-level control of the HWP. This maintains an updated
    HWPState containing state info pertaining to HWP agents. Additionally, it
    contains a state-machine for controlling the HWP based on the ControlState.


    Attributes
    ----------------
    agent : OCSAgent
        OCS agent instance
    args : argparse.Namespace
        Argument namespace
    hwp_state : HWPState
        Class containing most recent state information for the HWP
    control_state : ControlState
        Current control_state object. This will be used to determine what
        commands to issue to HWP agents.
    forward_is_cw : bool
        True if the PID "forward" direction is clockwise, False if CCW.
    """

    def __init__(self, agent, args):
        self.agent = agent
        self.args = args

        self.sleep_time = args.sleep_time
        self.log = agent.log

        self.ybco_lakeshore_id = args.ybco_lakeshore_id
        self.ybco_temp_field = args.ybco_temp_field
        self.ybco_temp_thresh = args.ybco_temp_thresh

        self.hwp_encoder_id = args.hwp_encoder_id
        self.hwp_pmx_id = args.hwp_pmx_id
        self.hwp_pid_id = args.hwp_pid_id
        self.ups_id = args.ups_id

        self.hwp_state = HWPState.from_args(args)
        self.gripper_iboot_id = args.gripper_iboot_id
        self.driver_iboot_id = args.driver_iboot_id
        self.control_state_machine = ControlStateMachine()
        self.forward_is_cw = args.forward_dir == 'cw'

        self.driver_power_agent_type = args.driver_power_agent_type
        self.driver_iboot_outlets = args.driver_iboot_outlets
        self.driver_power_cycle_twice = args.driver_power_cycle_twice
        self.driver_power_cycle_wait_time = args.driver_power_cycle_wait_time

    def _get_hwp_clients(self):
        def get_client(id):
            args = []
            if 'SITE_HTTP' in os.environ:
                args += [f"--site-http={os.environ['SITE_HTTP']}"]
            if id is None:
                return None
            try:
                return OCSClient(id, args=args)
            except ControlClientError:
                self.log.error("Could not connect to client: {id}", id=id)
                return None

        return HWPClients(
            encoder=get_client(self.hwp_encoder_id),
            pmx=get_client(self.hwp_pmx_id),
            pid=get_client(self.hwp_pid_id),
            pcu=get_client(self.args.hwp_pcu_id),
            ups=get_client(self.ups_id),
            lakeshore=get_client(self.ybco_lakeshore_id),
            gripper_iboot=get_client(self.gripper_iboot_id),
            driver_iboot=get_client(self.driver_iboot_id),
        )

    @ocs_agent.param('test_mode', type=bool, default=False)
    def monitor(self, session, params):
        """monitor()

        **Process** -- Monitors various HWP related HK systems.

        This operation has three main steps:

        - Query session data for all HWP and HWP adjacent agents. Session info for each
          queried operation will be stored in the ``monitored_sessions`` field of the
          session data. See the docs for the ``get_op_data`` function for information on
          what info will be saved.
        - Parse session-data from monitored operations to create the ``state`` dict,
          containing info such as ``ybco_temp`` and ``hwp_freq``.
        - Determine subsystem actions based on the HWP state, which will be stored in
          the ``actions`` dict which can be read by hwp subsystems to initiate a
          shutdown

        An example of the session data, along with possible options for status
        strings can be seen below::

            >>> response.session['data']

                {'timestamp': 1601924482.722671,
                'monitored_sessions': {
                    'encoder': {
                        'agent_id': 'test',
                        'data': <session data for test.acq>,
                        'op_name': 'acq',
                        'status': 'ok',  # See ``get_op_data`` docstring for choices
                        'timestamp': 1680273288.6200094},
                    },
                    'rotation': {see above},
                    'temperature': {see above},
                    'ups': {see above}
                    'iboot': {see above}},
                # State data parsed from monitored sessions
                'state': {
                    'hwp_freq': None,
                    'ybco_temp': 20.0,
                    'ybco_temp_status': 'ok',  # `no_data`, `ok`, or `over`
                    'ybco_temp_thresh': 75.0,
                    'ups_battery_current': 0,
                    'ups_battery_voltage': 136,
                    'ups_estimated_minutes_remaining': 50,
                    'ups_minutes_remaining_thresh': 45.0,
                    'ups_output_source': 'normal'  # See UPS agent docs for choices
                },
                 # Subsystem action recommendations determined from state data
                'actions': {
                    'pmx': 'ok'  # 'ok', 'stop', or 'no_data'
                    'gripper': 'ok'  # 'ok', 'stop', or 'no_data'
                }}
        """
        pm = Pacemaker(1. / self.sleep_time)
        test_mode = params.get('test_mode', False)

        session.data = {
            'timestamp': time.time(),
            'monitored_sessions': {},
            'hwp_state': {},
            'actions': {},
        }

        kw = {'test_mode': test_mode, 'log': self.log}

        while session.status in ['starting', 'running']:
            session.data['timestamp'] = time.time()

            # 1. Gather data from relevant operations
            temp_op = get_op_data(self.ybco_lakeshore_id, 'acq', **kw)
            enc_op = get_op_data(self.hwp_encoder_id, 'acq', **kw)
            pmx_op = get_op_data(self.hwp_pmx_id, 'main', **kw)
            pid_op = get_op_data(self.hwp_pid_id, 'main', **kw)
            ups_op = get_op_data(self.ups_id, 'acq', **kw)

            session.data['monitored_sessions'] = {
                'temperature': temp_op,
                'encoder': enc_op,
                'pmx': pmx_op,
                'pid': pid_op,
                'ups': ups_op,
            }

            # gather state info
            self.hwp_state.update_pid_state(pid_op)
            self.hwp_state.update_pmx_state(pmx_op)
            self.hwp_state.update_temp_state(temp_op)
            self.hwp_state.update_ups_state(ups_op)
            self.hwp_state.update_enc_state(enc_op)

            if self.hwp_state.driver_iboot is not None:
                self.hwp_state.driver_iboot.update()
            if self.hwp_state.gripper_iboot is not None:
                self.hwp_state.gripper_iboot.update()
            if self.hwp_state.acu is not None:
                self.hwp_state.acu.update()

            session.data['hwp_state'] = asdict(self.hwp_state)

            # Get actions for each hwp subsystem
            session.data['actions'] = {
                'pmx': self.hwp_state.pmx_action,
                'gripper': self.hwp_state.gripper_action,
            }

            if test_mode:
                break

            pm.sleep()

        return True, "Monitor process stopped"

    def _stop_monitor(self, session, params):
        session.status = 'stopping'
        return True, 'Stopping monitor process'

    @ocs_agent.param('test_mode', type=bool, default=False)
    def spin_control(self, session, params):
        """spin_control()

        **Process** - Process to manage the spin-state for HWP agents. This will
        issue commands to various HWP agents depending on the current control
        state.

        Args
        ----------
        test_mode : bool
            If True, spin_control loop will run a single update iteration before
            exiting. This is useful for testing actions.

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {
                'current_action': <Encoded action>,
                'action_history': List[Encoded action]
                'timestammp': <time.time()>
            }
        """
        clients = self._get_hwp_clients()

        while session.status in ['starting', 'running']:
            self.control_state_machine.update(clients, self.hwp_state)
            session.data = {
                'current_action': self.control_state_machine.action.encode(),
                'action_history': [a.encode() for a in self.control_state_machine.action_history],
                'timestamp': time.time()
            }
            if params['test_mode']:
                break
            time.sleep(1)
        return True, "Finished spin control process"

    def _stop_spin_control(self, session, params):
        session.status = 'stopping'
        return True, 'Stopping spin control process'

    @ocs_agent.param('target_freq', type=float)
    @ocs_agent.param('freq_tol', type=float, default=0.05)
    @ocs_agent.param('freq_tol_duration', type=float, default=10)
    def pid_to_freq(self, session, params):
        """pid_to_freq(target_freq=2.0, freq_thresh=0.05, freq_thresh_duration=10)

        **Task** - Sets the control state to PID the HWP to the given ``target_freq``.

        Args
        -------
        target_freq : float
            Target frequency of the HWP (Hz). This is aa signed float where
            positive values correspond to counter-clockwise motion, as seen when
            looking at the cryostat from the sky.
        freq_thresh : float
            Frequency threshold (Hz) for determining when the HWP is at the target frequency.
        freq_thresh_duration : float
            Duration (seconds) for which the HWP must be within ``freq_thresh`` of the
            ``target_freq`` to be considered successful.

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': True}
            }
        """
        if params['target_freq'] >= 0:
            d = '0' if self.forward_is_cw else '1'
        else:
            d = '1' if self.forward_is_cw else '0'

        state = ControlState.PIDToFreq(
            target_freq=np.abs(params['target_freq']),
            freq_tol=params['freq_tol'],
            freq_tol_duration=params['freq_tol_duration'],
            direction=d
        )
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"

    @ocs_agent.param('voltage', type=float)
    @ocs_agent.param('direction', type=str, choices=['cw', 'ccw'], default='cw')
    def set_const_voltage(self, session, params):
        """set_const_voltage(voltage=1.0)

        **Task** - Sets the control state set the PMX to a constant voltage.

        Args
        -------
        voltage : float
            Voltage to set the PMX to (V).
        direction : str
            Direction of the HWP. Must be one of ``cw`` or ``ccw``,
            corresponding to the clockwise and counter-clockwise directions of
            the HWP, as seen when looking at the cryostat from the sky.

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': True}
            }
        """
        if params['direction'] == 'cw':
            d = '0' if self.forward_is_cw else '1'
        else:
            d = '1' if self.forward_is_cw else '0'
        state = ControlState.ConstVolt(
            voltage=params['voltage'],
            direction=d
        )
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"

    @ocs_agent.param('freq_tol', type=float, default=0.05)
    @ocs_agent.param('freq_tol_duration', type=float, default=10)
    @ocs_agent.param('brake_voltage', type=float, default=10.)
    def brake(self, session, params):
        """brake(freq_thresh=0.05, freq_thresh_duration=10, brake_voltage=10)

        **Task** - Sets the control state to brake the HWP.

        Args
        -------
        freq_thresh : float
            Frequency threshold (Hz) for determining when the HWP is at the target frequency.
        freq_thresh_duration : float
            Duration (seconds) for which the HWP must be within ``freq_thresh`` of the
            ``target_freq`` to be considered successful.
        brake_voltage: float
            Voltage to use when braking the HWP.

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': True}
            }
        """
        state = ControlState.Brake(
            freq_tol=params['freq_tol'],
            freq_tol_duration=params['freq_tol_duration'],
            brake_voltage=params['brake_voltage'],
        )
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"

    def pmx_off(self, session, params):
        """pmx_off()

        **Task** - Sets the control state to turn off the PMX.

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': True}
            }
        """
        state = ControlState.PmxOff()
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"

    def abort_action(self, session, params):
        """abort_action()

        **Task** - Aborts the current action, setting the control state to Idle

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Idle'},
                'state_history': List[ConrolState],
                'success': False}
            }
        """
        state = ControlState.Idle()
        action = self.control_state_machine.request_new_action(state)
        session.data['action'] = action.encode()
        return True, "Set state to idle"

    def enable_driver_board(self, session, params):
        """enable_driver_board()

        **Task** - Enables the HWP driver board

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': False}
            }
        """
        kw = {
            'driver_power_agent_type': self.driver_power_agent_type,
            'outlets': self.driver_iboot_outlets,
            'cycle_twice': self.driver_power_cycle_twice,
            'cycle_wait_time': self.driver_power_cycle_wait_time,
        }
        state = ControlState.EnableDriverBoard(**kw)
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"

    def disable_driver_board(self, session, params):
        """disable_driver_board()

        **Task** - Disables the HWP driver board

        Notes
        --------

        Example of ``session.data``::

            >>> session['data']
            {'action':
                {'action_id': 3,
                'completed': True,
                'cur_state': {'class': 'Done', 'msg': None, 'success': True},
                'state_history': List[ConrolState],
                'success': False}
            }
        """
        kw = {
            'driver_power_agent_type': self.driver_power_agent_type,
            'outlets': self.driver_iboot_outlets,
        }
        state = ControlState.DisableDriverBoard(**kw)
        action = self.control_state_machine.request_new_action(state)
        action.sleep_until_complete(session=session)
        return action.success, f"Completed with state: {action.cur_state_info.state}"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')

    pgroup.add_argument('--sleep-time', type=float, default=2.)
    pgroup.add_argument('--ybco-lakeshore-id',
                        help="Instance ID for lakeshore reading out HWP temp")
    pgroup.add_argument('--ybco-temp-field',
                        help='Field name of lakeshore channel reading out HWP temp')
    pgroup.add_argument('--ybco-temp-thresh', type=float,
                        help="Threshold for HWP temp.")
    pgroup.add_argument('--hwp-encoder-id',
                        help="Instance id for HWP encoder agent")
    pgroup.add_argument('--hwp-pmx-id',
                        help="Instance ID for HWP pmx agent")
    pgroup.add_argument('--hwp-pid-id',
                        help="Instance ID for HWP pid agent")
    pgroup.add_argument('--hwp-pcu-id',
                        help="Instance ID for HWP PCU agent")
    pgroup.add_argument('--ups-id', help="Instance ID for UPS agent")
    pgroup.add_argument('--ups-minutes-remaining-thresh', type=float,
                        help="Threshold for UPS minutes remaining before a "
                             "shutdown is triggered")

    pgroup.add_argument(
        '--driver-iboot-id',
        help="Instance ID for IBoot-PDU agent that powers the HWP Driver board")
    pgroup.add_argument(
        '--driver-iboot-outlets', nargs='+', type=int,
        help="Outlets for driver iboot power")
    pgroup.add_argument(
        '--driver-power-cycle-twice', action='store_true',
        help="If set, will power cycle the driver board twice on enable")
    pgroup.add_argument(
        '--driver-power-cycle-wait-time', type=float, default=60 * 5,
        help="Wait time between power cycles on enable (sec)")
    pgroup.add_argument(
        '--driver-power-agent-type', choices=['iboot', 'synaccess'], default=None,
        help="Type of agent used for controlling the driver power")

    pgroup.add_argument(
        '--gripper-iboot-id',
        help="Instance ID for IBoot-PDU agent that powers the gripper controller")
    pgroup.add_argument(
        '--gripper-iboot-outlets', nargs='+', type=int,
        help="Outlets for gripper iboot power")
    pgroup.add_argument(
        '--gripper-power-agent-type', choices=['iboot', 'synaccess'], default=None,
        help="Type of agent used for controlling the gripper power")

    pgroup.add_argument(
        '--acu-instance-id',
        help="Instance ID for the ACU agent. This is required for checks of ACU "
             "postiion and velocity before HWP commands."
    )
    pgroup.add_argument(
        '--acu-min-el', type=float, default=48.0,
        help="Min elevation that HWP spin up is allowed",
    )
    pgroup.add_argument(
        '--acu-max-el', type=float, default=90.0,
        help="Max elevation that HWP spin up is allowed",
    )
    pgroup.add_argument(
        '--acu-max-time-since-update', type=float, default=30.0,
        help="Max amount of time since last ACU update before allowing HWP spin up",
    )

    pgroup.add_argument('--forward-dir', choices=['cw', 'ccw'], default="cw",
                        help="Whether the PID 'forward' direction is cw or ccw")
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='HWPSupervisor',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    hwp = HWPSupervisor(agent, args)

    agent.register_process('monitor', hwp.monitor, hwp._stop_monitor,
                           startup=True)
    agent.register_process(
        'spin_control', hwp.spin_control, hwp._stop_spin_control, startup=True)
    agent.register_task('pid_to_freq', hwp.pid_to_freq)
    agent.register_task('set_const_voltage', hwp.set_const_voltage)
    agent.register_task('brake', hwp.brake)
    agent.register_task('pmx_off', hwp.pmx_off)
    agent.register_task('abort_action', hwp.abort_action)
    agent.register_task('enable_driver_board', hwp.enable_driver_board)
    agent.register_task('disable_driver_board', hwp.disable_driver_board)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
