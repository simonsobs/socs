from ocs.ocs_client import OCSClient
from ocs import site_config
import time
import argparse


class ManagedSmurfInstance:
    def __init__(self, address, expire_time=20):
        self.address = address
        self.instance_id = address.split('.')[-1]
        self.agent_session_id = None
        self.last_refresh = 0
        self.expire_time = expire_time
        self.client = OCSClient(self.instance_id)
        self.status = {}
        self.stream_id = None

    def register_heartbeat(self, op_codes, feed):
        self.last_refresh = time.time()

    @property
    def expired(self):
        return time.time() - self.last_refresh > self.expire_time

    def update_status(self):
        api = self.client._client.get_api()
        status = {}
        for (name, session, _) in api['tasks']:
            status[name] = session
        for (name, session, _) in api['processes']:
            status[name] = session
        self.status = status

        state_data = self.status['check_state'].get('data')
        if state_data is not None:
            self.stream_id = state_data.get('stream_id')

    def start_op(self, op_name, params):
        self.client._client.request('start', op_name, params=params)

    def stop_op(self, op_name, params):
        self.client._client.request('stop', op_name, params=params)


class MultiSmurfManager:
    def __init__(self):
        self.agent = agent
        self.smurfs = {}

        self.agent.subscribe_on_start(
            self._register_heartbeat, 'observatory..feeds.heartbeat',
            options={'match': 'wildcard'}
        )

    def _register_heartbeat(self, _data):
        op_codes, feed = _data
        if feed.get('agent_class') != 'PysmurfController':
            return

        addr = feed['agent_address']

        s = self.smurfs.setdefault(addr, ManagedSmurfInstance(addr))
        s.register_heartbeat(op_codes, feed)

    def monitor(self, session, params):
        session.set_status('running')
        while session.status in ['starting', 'running']:
            for s in self.smurfs.values():
                if not s.expired:
                    s.update_status()
            time.sleep(10)
        return True, "Stopped monitor process"

    def _stop_monitor(self, session, params):
        session.set_status('stopping')

    def _get_smurfs_by_streamids(self, stream_ids=None):
        smurfs = {}
        if stream_ids is None:
            for name, smurf in self.smurfs.items():
                if not smurf.expired:
                    smurfs[smurf.stream_id] = smurf
        else:
            for stream_id in stream_ids:
                for smurf in self.smurfs.values():
                    if smurf.stream_id == stream_id:
                        smurfs[stream_id] = smurf
                        break
                else:
                    raise ValueError(
                        f"Could not find managed smurf with "
                        f"stream_id: {stream_id}"
                    )
        return smurfs

    def run_op(self, op_name, session, params):
        stream_ids = params.get('stream_ids')
        smurfs = self._get_smurfs_by_streamids(stream_ids)

        for smurf in smurfs.values():
            session.data['stream_ids'].append(smurf.stream_id)
            smurf.start_op(op_name, params)

        session.set_status('running')
        while True:
            time.sleep(10)
            print("HERE")


def make_parser(parser=None):
    """
    Builds argsparse parser, allowing sphinx to auto-document it.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='MultiSmurfManager', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args)

    runner.run(agent, auto_reconnect=True)
