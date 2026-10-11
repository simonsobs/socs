import argparse
import os
import time

import txaio
import yaml

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker


class SmurfPcieMonitorAgent:
    """Agent to monitor PCIe card registers via the smurf-pcie rogue server."""

    def __init__(self, agent, args):
        self.agent = agent
        self.log = agent.log
        self.zmq_addr = args.zmq_addr
        self.poll_interval = args.poll_interval
        self._client = None

        with open(args.reg_config, 'r') as f:
            config = yaml.safe_load(f)
        self.registers = config['registers']

        agg_params = {'frame_length': 10 * 60}
        agent.register_feed('pcie_registers', record=True,
                            agg_params=agg_params, buffer_time=1.)

    def _connect(self):
        """Connect to the rogue ZMQ server. Returns True on success."""
        import pyrogue.interfaces
        try:
            if self._client is not None:
                try:
                    self._client.stop()
                except Exception:
                    pass
                self._client = None
            host, port = self.zmq_addr.rsplit(':', 1)
            self._client = pyrogue.interfaces.VirtualClient(
                addr=host,
                port=int(port),
            )
            self._client.root.Core
            self.log.info("Connected to rogue server at {addr}",
                          addr=self.zmq_addr)
            return True
        except Exception as e:
            self.log.error("Failed to connect to rogue server: {e}", e=e)
            self._client = None
            return False

    def _disconnect(self):
        """Disconnect from the rogue ZMQ server."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def _read_registers(self):
        """Read all configured registers. Returns dict or None on failure."""
        if self._client is None:
            return None
        data = {}
        for reg in self.registers:
            try:
                node = self._client.root
                for part in reg['path'].split('.'):
                    if '[' in part:
                        name, idx = part.rstrip(']').split('[')
                        node = getattr(node, name)[int(idx)]
                    else:
                        node = getattr(node, part)
                val = node.get()
                data[reg['field_name']] = val
            except Exception as e:
                self.log.error("Error reading {p}: {e}",
                               p=reg['path'], e=e)
                raise ConnectionError(f"Read failed for {reg['path']}")
        return data

    def acq(self, session, params):
        """acq()

        **Process** -- Acquire PCIe card register data.

        Connects to the smurf-pcie rogue server and periodically reads
        the configured registers, publishing data to the
        ``pcie_registers`` feed.

        Notes:
            An example of the session data::

                >>> response.session['data']
                {'timestamp': 1678983237.8,
                 'fpga_version': 50331648,
                 'uptime_cnt': 123456,
                 'device_id': 1234}

        """
        pacemaker = Pacemaker(1. / self.poll_interval)

        while session.status in ['starting', 'running']:
            if self._client is None:
                if not self._connect():
                    self.log.warn(
                        "Not connected. Retrying in {t} s.",
                        t=self.poll_interval)
                    pacemaker.sleep()
                    continue

            try:
                data = self._read_registers()
            except ConnectionError:
                self.log.warn("Connection lost. Will reconnect.")
                self._disconnect()
                pacemaker.sleep()
                continue

            if data:
                now = time.time()
                session.data = {**data, 'timestamp': now}
                msg = {
                    'timestamp': now,
                    'block_name': 'pcie_registers',
                    'data': data,
                }
                self.agent.publish_to_feed('pcie_registers', msg)

            pacemaker.sleep()

        self._disconnect()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        session.set_status('stopping')


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--zmq-addr', required=True,
                        help='ZMQ server address (host:port) of the '
                             'smurf-pcie rogue server')
    pgroup.add_argument('--reg-config', required=True,
                        help='Path to YAML file listing register paths '
                             'to monitor')
    pgroup.add_argument('--poll-interval', type=float, default=30.,
                        help='Seconds between register reads (default: 30)')
    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args('SmurfPcieMonitorAgent', parser=parser,
                                  args=args)
    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))
    agent, runner = ocs_agent.init_site_agent(args)
    monitor = SmurfPcieMonitorAgent(agent, args)
    agent.register_process('acq', monitor.acq, monitor._stop_acq,
                           startup=True)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
