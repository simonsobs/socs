from ocs import ocs_agent, site_config, client_t, ocs_twisted
import json
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, protocol
import sys


class Receiver:
    def __init__(self, controller, addr):
        self.addr = addr
        self.controller = controller
        self.agent = controller.agent
        self.log = self.agent.log

        self.types = []
        self.last_seq = None

    def recv(self, d):

        if self.last_seq is None:
            print("New sequence: {}".format(d['seq_no']))
        else:
            delta = d['seq_no'] - self.last_seq
            if delta != 1:
                self.log.info('Sequence jump: %i + %i' % (self.last_seq, delta))
                self.types = []

        self.last_seq = d['seq_no']
        if not d['type'] in self.types:
            self.log.info('New type: %s at %i' % (d['type'], d['seq_no']))
            self.types.append(d['type'])

        if d['type'] in ['start', 'stop']:
            print(d)


class PysmurfScriptProtocol(protocol.ProcessProtocol):
    pass


class PysmurfController(DatagramProtocol):
    def __init__(self, agent, udp_ip: str, udp_port: int):
        self.agent = agent
        self.log = agent.log
        self.lock = ocs_twisted.TimeoutLock()

        self.udp_ip = udp_ip
        self.udp_port = udp_port

        self.receivers = {}

    def datagramReceived(self, data, addr):
        try:
            r = self.receivers[addr]
        except KeyError:
            self.receivers[addr] = Receiver(self, addr)
            r = self.receivers[addr]

        r.recv(json.loads(data))

    def run_script(self, session, params=None):
        """
        Runs a pysmurf control script.

        Args:

            script (string): path to the script you wish to run
            args (list, optional):
                List of command line arguments to pass to the script.
                Defaults to [].
        """
        if params is None:
            params = {}

        script_file = params['script']
        args = params.get('args', [])

        reactor.callFromThread(self._launch_script, script_file, args)
        return True, "Started script {}".format(script_file)

    def _launch_script(self, script_file, args):
        pyth = sys.executable
        cmd = [pyth, script_file, args]

        prot = PysmurfScriptProtocol()
        reactor.spawnProcess(prot, cmd[0], cmd)


if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--udp-port')
    pgroup.add_argument('--udp-ip')

    args = parser.parse_args()

    site_config.reparse_args(args, 'PysmurfController')

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args.udp_ip, int(args.udp_port))

    agent.register_task('run_script', controller.run_script)

    reactor.listenUDP(int(args.udp_port), controller)

    runner.run(agent, auto_reconnect=True)
