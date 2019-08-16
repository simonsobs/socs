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
import hashlib

from socs.util import get_db_connection, get_md5sum


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
                          data=data.strip().decode('utf-8'))

    def errReceived(self, data):
        self.log.error(data)

    def processEnded(self, status):
        # if self.log is not None:
        #     self.log.info("Process ended: {reason}", reason=status)
        self.end_status = status


class PysmurfController(DatagramProtocol):
    def __init__(self, agent, udp_ip: str, udp_port: int, cache_len=10):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = ocs_twisted.TimeoutLock()

        self.prot = None

        # For monitoring pysmurf publisher
        self.udp_ip = udp_ip
        self.udp_port = udp_port

        self.file_cache = []
        self.cache_len = cache_len

        self.agent.register_feed('pysmurf_files')

        self.sql_config = {
            'user': os.environ["MYSQL_USER"],
            'passwd': os.environ["MYSQL_PASSWORD"],
            'database': 'files'
        }
        db_host = os.environ.get('MYSQL_HOST')
        if db_host is not None:
            self.sql_config['host'] = db_host

        with get_db_connection(**self.sql_config) as con:
            cur = con.cursor()
            cur.execute("SHOW TABLES;")
            table_names = [x[0] for x in cur.fetchall()]
            if not 'pysmurf_files' in table_names:
                self.log.info("Could not find pysmurf_files table. "
                              "Creating one now....")

                cur.execute("""
                    CREATE TABLE pysmurf_files (
                        id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        path VARCHAR(260) UNIQUE NOT NULL,
                        timestamp TIMESTAMP,
                        format VARCHAR(32),
                        type VARCHAR(32),
                        site VARCHAR(32),
                        instance_id VARCHAR(32),
                        copied TINYINT(1),
                        failed_copy_attempts INT,
                        md5sum BINARY(16) NOT NULL
                    );
                """)

                con.commit()
            else:
                self.log.info("Found existing table pysmurf_files.")

    def datagramReceived(self, _data, addr):
        """Function called whenever data is passed to UDP socket"""
        data = json.loads(_data)

        if data['type'] in ['data_file', 'plot']:
            self.log.info("New file: {fname}", fname=data['payload']['path'])
            d = data['payload']
            cols = ['path', 'format', 'type', 'site', 'instance_id',
                    'copied', 'failed_copy_attempts', 'md5sum']

            md5sum = get_md5sum(d['path'])
            site, instance_id = self.agent.agent_address.split('.')
            query = f"""
                INSERT INTO pysmurf_files ({', '.join(cols)}) VALUES (
                    '{d['path']}', '{d['format']}', '{d['type']}', '{site}', 
                    '{instance_id}', 0, 0, UNHEX('{md5sum}')                    
                )
            """

            with get_db_connection(**self.sql_config) as con:
                cur = con.cursor()
                cur.execute(query)
                self.log.info(f"Inserted {d['path']} into database")
                con.commit()

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
        cmd = [pyth, '-u', script_file] + args
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

    agent.register_process('run', controller.run_script, controller.abort_script)

    reactor.listenUDP(int(args.udp_port), controller)

    runner.run(agent, auto_reconnect=True)
