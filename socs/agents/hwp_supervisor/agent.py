import argparse
import time
from dataclasses import dataclass
from typing import Optional

import txaio
from ocs import client_http, ocs_agent, site_config
from ocs.client_http import ControlClientError
from ocs.ocs_client import OCSClient, OCSReply
from ocs.ocs_twisted import Pacemaker


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
        log = txaio.make_logger()  # pyright: ignore

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

    client = site_config.get_control_client(agent_id)
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
    rotation: Optional[OCSClient] = None
    ups: Optional[OCSClient] = None
    lakeshore: Optional[OCSClient] = None


class HWPSupervisor:
    def __init__(self, agent, args):
        self.agent = agent
        self.args = args

        self.sleep_time = args.sleep_time
        self.log = agent.log

        self.hwp_lakeshore_id = args.hwp_lakeshore_id
        self.hwp_temp_field = args.hwp_temp_field
        self.hwp_temp_thresh = args.hwp_temp_thresh

        self.hwp_encoder_id = args.hwp_encoder_id
        self.hwp_rotation_id = args.hwp_rotation_id
        self.ups_id = args.ups_id
        self._ups_oid = None
        self.ups_minutes_remaining_thresh = args.ups_minutes_remaining_thresh

    def _get_hwp_clients(self):
        def get_client(id):
            if id is None:
                return None
            try:
                return OCSClient(id)
            except ControlClientError:
                self.log.error("Could not connect to client: {id}", id=id)
                return None

        return HWPClients(
            encoder=get_client(self.hwp_encoder_id),
            rotation=get_client(self.hwp_rotation_id),
            ups=get_client(self.ups_id),
            lakeshore=get_client(self.hwp_lakeshore_id)
        )

    def _get_rotator_action(self, state):
        # First check if either ups or temp are beyond a threshold
        hwp_temp = state['hwp_temp']
        if hwp_temp is not None and self.hwp_temp_thresh is not None:
            if hwp_temp > self.hwp_temp_thresh:
                return 'stop'

        minutes_remaining = state['ups_estimated_minutes_remaining']
        if minutes_remaining is not None:
            if minutes_remaining < self.ups_minutes_remaining_thresh:
                return 'stop'

        # If either hwp_temp or ups state is None, return no_data
        for val in [hwp_temp, minutes_remaining]:
            if val is None:
                return 'no_data'

        return 'ok'

    def _get_gripper_action(self, state):
        """
        Gets the gripper action based on the current state of the system.
        This will only report 'stop' if the rot_action is 'stop' and the hwp
        freq is exactly 0. The gripper agent should not grip the hwp in a
        no-data event.
        """
        rot_action = self._get_rotator_action(state)
        if rot_action == 'ok':
            return 'ok'
        if rot_action == 'no_data':
            return 'no_data'

        hwp_freq = state['hwp_freq']
        if hwp_freq is None:
            return 'no_data'
        elif hwp_freq > 0:
            return 'ok'
        else:  # Only grip if the hwp_freq is exactly 0
            return 'stop'

    def _update_state_temp(self, temp_op, state):
        """
        Updates state dict with temperature data.
        """
        state.update({
            'hwp_temp': None,
            'hwp_temp_status': 'no_data',
            'hwp_temp_thresh': self.hwp_temp_thresh,
        })

        if temp_op['status'] != 'ok':
            return state

        fields = temp_op['data']['fields']
        if self.hwp_temp_field not in fields:
            return state

        hwp_temp = fields[self.hwp_temp_field]['T']
        state['hwp_temp'] = hwp_temp
        state['hwp_temp_status'] = 'ok'

        if self.hwp_temp_thresh is not None:
            if hwp_temp > self.hwp_temp_thresh:
                state['hwp_temp_status'] = 'over'

        return state

    def _update_state_ups(self, ups_op, state):
        """
        Updates state dict with UPS data.
        """
        ups_keymap = {
            'ups_output_source': ('upsOutputSource', 'description'),
            'ups_estimated_minutes_remaining': ('upsEstimatedMinutesRemaining', 'status'),
            'ups_battery_voltags': ('upsBatteryVoltage', 'status'),
            'ups_battery_current': ('upsBatteryCurrent', 'status'),
        }

        state['ups_minutes_remaining_thresh'] = self.ups_minutes_remaining_thresh

        if ups_op['status'] != 'ok':
            for k in ups_keymap:
                state[k] = None
            return

        # get oid
        data = ups_op['data']
        for k in data:
            if k.startswith('upsOutputSource'):
                ups_oid = k.split('_')[1]
                break
        else:
            self.log.error(f"Could not find OID for {self.ups_id}")
            return

        for k, field in ups_keymap.items():
            state[k] = data[f'{field[0]}_{ups_oid}'][field[1]]

        return state

    @ocs_agent.param('test_mode', type=bool, default=False)
    def monitor(self, session, params):
        """monitor()

        *Process* -- Monitors various HWP related HK systems.

        This operation has three main steps:

        - Query session data for all HWP and HWP adjacent agents. Session info for each
          queried operation will be stored in the ``monitored_sessions`` field of the
          session data. See the docs for the ``get_op_data`` function for information on
          what info will be saved.
        - Parse session-data from monitored operations to create the ``state`` dict,
          containing info such as ``hwp_temp`` and ``hwp_freq``.
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
                    'ups': {see above}},
                # State data parsed from monitored sessions
                'state': {
                    'hwp_freq': None,
                    'hwp_temp': 20.0,
                    'hwp_temp_status': 'ok',  # `no_data`, `ok`, or `over`
                    'hwp_temp_thresh': 75.0,
                    'ups_battery_current': 0,
                    'ups_battery_voltags': 136,
                    'ups_estimated_minutes_remaining': 50,
                    'ups_minutes_remaining_thresh': 45.0,
                    'ups_output_source': 'normal'  # See UPS agent docs for choices
                },
                 # Subsystem action recommendations determined from state data
                'actions': {
                    'rotation': 'ok'  # 'ok', 'stop', or 'no_data'
                    'grippder': 'ok'  # 'ok', 'stop', or 'no_data'
                }}
        """
        pm = Pacemaker(1. / self.sleep_time)
        test_mode = params.get('test_mode', False)

        session.data = {
            'timestamp': time.time(),
            'monitored_sessions': {},
            'state': {},
            'actions': {}
        }

        kw = {'test_mode': test_mode, 'log': self.log}

        while session.status in ['starting', 'running']:
            session.data['timestamp'] = time.time()

            # 1. Gather data from relevant operations
            temp_op = get_op_data(self.hwp_lakeshore_id, 'acq', **kw)
            enc_op = get_op_data(self.hwp_encoder_id, 'acq', **kw)
            rot_op = get_op_data(self.hwp_rotation_id, 'iv_acq', **kw)
            ups_op = get_op_data(self.ups_id, 'acq', **kw)

            session.data['monitored_sessions'] = {
                'temperature': temp_op,
                'encoder': enc_op,
                'rotation': rot_op,
                'ups': ups_op
            }

            # gather state info
            state = {}
            self._update_state_temp(temp_op, state)
            self._update_state_ups(ups_op, state)

            if enc_op['status'] == 'ok':
                state['hwp_freq'] = enc_op['data']['approx_hwp_freq']
            else:
                state['hwp_freq'] = None

            session.data['state'] = state

            # Get actions for each hwp subsystem
            session.data['actions'] = {
                'rotation': self._get_rotator_action(state),
                'gripper': self._get_gripper_action(state),
            }

            if test_mode:
                break

            pm.sleep()

        return True, "Monitor process stopped"

    def _stop_monitor(self, session, params):
        session.status = 'stopping'
        return True, 'Stopping monitor process'

    @ocs_agent.param('forward', type=bool, default=True)
    @ocs_agent.param('freq', type=float)
    def spin_up(self, session, params):
        """spin_up(forward=True, freq=2.0)

        *Task* -- Sets the HWP to spin at a given frequency.

        An example of the session data::

            >>> response.session['data']

                {'forward': True,
                'commanded_freq': 2.0,
                'pid_freq': 1.2}
        """
        clients = self._get_hwp_clients()

        direction = '0' if params['forward'] else '1'
        clients.rotation.set_direction(direction=direction)
        session.add_message("Set rotation direction: forward={}".format(params['forward']))

        clients.rotation.declare_freq(freq=params['freq'])
        clients.rotation.tune_freq()
        clients.rotation.set_on()
        session.add_messsage("Tuning PID to {:.2f} Hz".format(params['freq']))

        session.data = {'forward': params['forward'],
                        'commanded_freq': params['freq'],
                        'pid_freq': 0}
        while True:
            _, _, s = clients.rotation.get_freq()
            cur_freq = s.data['freq']
            session.data['pid_freq'] = cur_freq
            if cur_freq - params['freq'] < 0.005:
                break
            time.sleep(0.5)

        return True, f'HWP spinning at {cur_freq:.2f} Hz'

    @ocs_agent.param('pid_freq_thresh', type=float, default=0.2)
    @ocs_agent.param('use_pid', type=bool, default=True)
    def spin_down(self, session, params):
        """spin_down(pid_freq_thresh=0.2, use_pid=True)

        *Task* -- Commands the HWP to spin down. If ``use_pid=True``, this will
        use the PID to quickly spin down the HWP. If ``use_pid=False``, this
        will tell the rotation agent to just cut the power.

        An example of the session data::

            >>> response.session['data']

                {'pid_freq': 0.6,
                 'pid_freq_thresh': 0.2,
                 'use_pid': True}
        """
        clients = self._get_hwp_clients()

        if not params.use_pid:
            clients.rotation.set_off()
            session.data = {
                'pid_freq': None,
                'pid_freq_thresh': params['pid_freq_thresh'],
                'use_pid': params['use_pid']
            }
            return True, "Commanded HWP to stop spinning"

        clients.rotation.tune_stop()
        clients.rotation.set_on()
        session.add_messsage("Tuning PID to stop")

        session.data = {
            'pid_freq_thresh': params.pid_freq_thresh,
            'use_pid': params.use_pid
        }
        while True:
            _, _, s = clients.rotation.get_freq()
            cur_freq = s.data['freq']
            session.data['pid_freq'] = cur_freq
            if cur_freq < params.pid_freq_thresh:
                break

        clients.rotation.set_off()
        return True, "Commanded HWP to stop spinning"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')

    pgroup.add_argument('--sleep-time', type=float, default=2.)

    pgroup.add_argument('--hwp-lakeshore-id',
                        help="Instance ID for lakeshore reading out HWP temp")
    pgroup.add_argument('--hwp-temp-field',
                        help='Field name of lakeshore channel reading out HWP temp')
    pgroup.add_argument('--hwp-temp-thresh', type=float,
                        help="Threshold for HWP temp.")

    pgroup.add_argument('--hwp-encoder-id',
                        help="Instance id for HWP encoder agent")
    pgroup.add_argument('--hwp-rotation-id',
                        help="Instance ID for rotation agent")
    pgroup.add_argument('--ups-id', help="Instance ID for UPS agent")
    pgroup.add_argument('--ups-minutes-remaining-thresh', type=float, default=30.,
                        help="Threshold for UPS minutes remaining before a "
                             "shutdown is triggered")

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
    agent.register_task('spin_up', hwp.spin_up)
    agent.register_task('spin_down', hwp.spin_down)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
