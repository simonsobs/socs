import argparse
import time
from collections import defaultdict

from ocs import client_http, ocs_agent, site_config
from ocs.ocs_client import OCSClient, OCSReply
from ocs.ocs_twisted import Pacemaker
import txaio


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
        self.log.warn('Error getting status: {e}', e=e)
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


    def parse_hwp_temp(self, op_data):
        if op_data['state'] != 'ok':
            return None, 'no_data'
        
        fields = op_data['data']['fields']
        if self.hwp_temp_field not in fields:
            return None, 'no_data'
        
        hwp_temp = fields[self.hwp_temp_field]['T']
        if hwp_temp > self.hwp_temp_thresh:
            return hwp_temp, 'over'
        else:
            return hwp_temp, 'ok'


    @ocs_agent.param('test_mode', type=bool)
    def monitor(self, session, params):
        """monitor()

        *Process* -- Monitors various HWP related HK systems
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
                'temperature': temp_op, 'encoder': enc_op, 'rotation': rot_op,
                'ups': ups_op
            }

            # Parse data for relevant info
            hwp_temp, hwp_temp_status = self.parse_hwp_temp(temp_op)

            hwp_freq = None
            if enc_op['status'] == 'ok':
                hwp_freq = enc_op['data']['approx_hwp_freq']
            
            # TODO: Add UPS state 

            session.data['state'] = {
                'hwp_temp': hwp_temp, 'hwp_temp_status': hwp_temp_status,
                'hwp_freq': hwp_freq,
            }

            # Get actions for each hwp subsystem
            if hwp_temp_status == 'over':
                rot_action = 'stop'
            elif hwp_temp_status == 'nodata':
                rot_action = 'no_data'
            elif hwp_temp_status == 'ok':
                rot_action = 'ok'

            # TODO: Add gripper and encoder action

            session.data['actions'] = {
                'rotation': rot_action
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
