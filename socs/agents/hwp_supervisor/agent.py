import argparse

import time

from ocs import ocs_agent,site_config, client_http
from ocs.ocs_twisted import Pacemaker
from ocs.ocs_client import OCSClient, OCSReply
from collections import defaultdict

class HWPSupervisor:
    def __init__(self, agent, args):
        self.agent = agent
        self.args = args

        self.sleep_time = args.sleep_time
        self.log = agent.log
        self.hwp_lakeshore_id = args.hwp_lakeshore_id
        self.hwp_temp_field = args.hwp_temp_field
        self.hwp_encoder_id = args.hwp_encoder_id
        self.hwp_rotation_id = args.hwp_rotation_id
        self.ups_id = args.ups_id

    def _parse_hwp_temp(self, d):
        """Parses session.data from the ls240.acq operation"""
        return {
            'temperature': d['fields'][self.hwp_temp_field]['T'],
            'timestamp': d['timestamp'],
        }

    def _get_op_data(self, agent_id, op_name, session_data_parser=None):
        """
        Process data from an agent operation, and formats it for the ``monitor``
        operation session data.

        Parameters
        --------------
        agent_id : str
            Instance ID of the agent
        op_name : str
            Operation from which to grab session data
        session_data_parser : func, optional
            Function to re-format the session.data object.
        """
        data = {
            'agent_id': agent_id,
            'op_name': op_name,
            'timestamp': time.time(),
            'data': None
        }
        if agent_id is None:
            data['status'] = 'no_agent_provided'
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

        try:
            if session_data_parser is not None:
                data['data'] = session_data_parser(session['data'])
            else:
                data['data'] = session['data']
            data['status'] = 'ok'
        except Exception as e:
            self.log.error("Error parsing session data for {agent_id}.{op}:\n{e}",
                            agent_id=agent_id, op=op_name, e=e)
            data['status'] = 'error_parsing_session_data'
            return data

        return data

    def monitor(self, session, params):
        """monitor()

        *Process* -- Monitors various HWP related HK systems
        """
        pm = Pacemaker(1./self.sleep_time)
        
        session.data = {
            'hwp_temperature': {},
            'hwp_encoder': {},
            'hwp_rotation': {},
            'ups': {},
            'timestamp': time.time()
        }

        while session.status in ['starting', 'running']:
            session.data['timestamp'] = time.time()

            session.data['hwp_temperature'].update(
                self._get_op_data(self.hwp_lakeshore_id, 'acq',
                                  session_data_parser=self._parse_hwp_temp))

            session.data['hwp_encoder'].update(
                self._get_op_data(self.hwp_encoder_id, 'acq'))

            session.data['hwp_rotation'].update(
                self._get_op_data(self.hwp_rotation_id, 'iv_acq'))

            session.data['ups'].update(self._get_op_data(self.ups_id, 'acq'))
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
    pgroup.add_argument('--hwp-lakeshore-id')
    pgroup.add_argument('--hwp-temp-field')
    pgroup.add_argument('--hwp-encoder-id')
    pgroup.add_argument('--hwp-rotation-id')
    pgroup.add_argument('--ups-id')

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
