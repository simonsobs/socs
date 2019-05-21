from ocs import ocs_agent, site_config, client_t, ocs_twisted
from ocs.ocs_agent import log_formatter
import json
from twisted.internet.protocol import DatagramProtocol
from twisted.internet import reactor, protocol
from twisted.internet.error import ProcessDone, ProcessTerminated
import sys

from twisted.logger import Logger, formatEvent, FileLogObserver
import time
import os


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
            self.log.info("{d}", d=d)


class PysmurfScriptProtocol(protocol.ProcessProtocol):
    def __init__(self, fname, log=None):
        self.fname = fname
        self.log = log
        self.end_status = None

    def connectionMade(self):
        print("Connection Made")
        self.transport.closeStdin()

    def outReceived(self, data):
        if self.log:
            self.log.info("{fname}: {data}",
                          fname=self.fname.split('/')[-1],
                          data=data.strip())

    def errReceived(self, data):
        self.log.error(data)

    def processEnded(self, status):
        # if self.log is not None:
        #     self.log.info("Process ended: {reason}", reason=status)
        self.end_status = status


class PysmurfController(DatagramProtocol):
    def __init__(self, agent, udp_ip: str, udp_port: int):
        self.agent = agent
        self.log = agent.log
        self.lock = ocs_twisted.TimeoutLock()

        self.udp_ip = udp_ip
        self.udp_port = udp_port

        self.receivers = {}
        self.prot = None

    def datagramReceived(self, data, addr):
        """Function called whenever data is passed to UDP socket"""
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
            log (string/bool, optional):
                Determines if and how the process's stdout should be logged.
                You can pass the path to a logfile, True to use the agent's log,
                or False to not log at all.

        """
        if params is None:
            params = {}

        if self.prot is not None:
            return False, "Process {} is already running".format(self.prot.fname)

        script_file = params['script']
        args = params.get('args', [])
        log_file = params.get('log', True)

        params = {'fname': script_file}

        if type(log_file) is str:
            fout = open(log_file, 'a')
            params['log'] = Logger(observer=FileLogObserver(fout, log_formatter))
        elif log_file:
            params['log'] = self.log
        else:
            params['log'] = None

        self.prot = PysmurfScriptProtocol(**params)
        pyth = sys.executable
        cmd = [pyth, script_file] + args
        self.log.info("{exec}, {cmd}", exec=pyth, cmd=cmd)
        reactor.callFromThread(
            reactor.spawnProcess, self.prot, pyth, cmd, env=os.environ
        )

        while self.prot.end_status is None:
            time.sleep(1)

        end_status = self.prot.end_status
        self.prot = None
        if isinstance(end_status.value, ProcessDone):
            return True, "Script has finished naturally"
        elif isinstance(end_status.value, ProcessTerminated):
            return False, "Script has been killed"

    def abort_script(self, session, params=None):
        """
        Aborts the currently running script
        """
        self.prot.transport.signalProcess('KILL')
        return True, "Aborting process"


if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--udp-port')
    pgroup.add_argument('--udp-ip')

    args = parser.parse_args()

    site_config.reparse_args(args, 'PysmurfController')

    agent, runner = ocs_agent.init_site_agent(args)
    controller = PysmurfController(agent, args.udp_ip, int(args.udp_port))

    agent.register_task('run', controller.run_script)
    agent.register_task('abort', controller.abort_script)

    reactor.listenUDP(int(args.udp_port), controller)

    runner.run(agent, auto_reconnect=True)
