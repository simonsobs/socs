import argparse
import time

import txaio
from ocs import client_http, ocs_agent, site_config
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
        log = txaio.make_logger()

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

        An example of the session data::

            >>> response.session['data']

                {'timestamp': 1601924482.722671,
                'monitored_sessions': {
                    'encoder': {
                        'agent_id': 'test',
                        'data': <session data for test.acq>,
                        'op_name': 'acq',
                        'status': 'ok',
                        'timestamp': 1680273288.6200094},
                    },
                    'rotation': {see above},
                    'temperature': {see above},
                    'ups': {see above}},
                # State data parsed from monitored sessions
                'state': {
                    'hwp_temp': None,
                    'hwp_temp_status': 'no_data',
                    'hwp_freq': None,
                },
                # Subsystem action recommendations determined from state data
                'actions': {
                    'rotation': 'no_data'
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

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
