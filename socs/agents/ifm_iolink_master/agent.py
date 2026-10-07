import argparse
import os
import time

import requests
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.ifm_iolink_master.drivers import (
    SENSOR_EXTRACTORS,
    extract_generic,
)

txaio.use_twisted()


class IFMIOLinkMasterAgent:
    """Monitor IO-Link sensors via an IFM DataLine IO-Link master.

    Works with any IFM DataLine IO-Link master that implements the IoT Core
    REST API (AL1340, AL1342, and other models sharing firmware 3.1.x).
    Reads all configured ports in a single HTTP request using getdatamulti,
    over a persistent keep-alive connection.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent.
    ip_address : str
        IP address of the IO-Link master (IoT port).
    ports_config : list of dict
        Each entry is ``{'port': int, 'sensor_type': str}``.
        sensor_type must be a key in SENSOR_EXTRACTORS or 'generic'.

    """

    def __init__(self, agent, ip_address, ports_config):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.url = f'http://{ip_address}'
        self.ports_config = ports_config
        self.session = None
        self.initialized = False
        self.take_data = False
        self.device_model = None

        agg_params = {'frame_length': 60, 'exclude_influx': False}
        self.agent.register_feed('iolink_sensors',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def _create_session(self):
        """Create or recreate a persistent HTTP session."""
        if self.session:
            try:
                self.session.close()
            except Exception:
                pass
        self.session = requests.Session()
        self.session.headers.update({'Connection': 'keep-alive'})

    def _post(self, payload, timeout=(5, 10)):
        """POST to the IO-Link master with retry-once on connection failure.

        Returns the parsed JSON response dict, or None on failure.
        """
        for attempt in range(2):
            try:
                r = self.session.post(self.url, json=payload, timeout=timeout)
                return r.json()
            except (requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError) as e:
                if attempt == 0:
                    self.log.warn(f"Connection failed ({e}), reconnecting...")
                    self._create_session()
                    time.sleep(1)
                else:
                    self.log.error(f"Connection failed on retry: {e}")
                    return None
        return None

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_iolink_master(self, session, params=None):
        """init_iolink_master(auto_acquire=False)

        **Task** - Connect to the IO-Link master and validate port
        configuration.

        Parameters
        ----------
        auto_acquire : bool, optional
            If True, start the acq process after initialization.
            Default is False.

        """
        with self.lock.acquire_timeout(0) as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            self._create_session()

            resp = self._post({"code": "request", "cid": -1,
                               "adr": "/devicetag/applicationtag/getdata"})
            if resp and resp.get('code') == 200:
                self.device_model = resp['data']['value']
                self.log.info(f"Connected to {self.device_model} "
                              f"at {self.ip_address}")
            else:
                self.log.error(f"Failed to identify device at "
                               f"{self.ip_address}: {resp}")
                return False, "Could not identify IO-Link master"

            for pc in self.ports_config:
                port = pc['port']
                expected = pc['sensor_type']
                adr = (f"/iolinkmaster/port[{port}]"
                       f"/iolinkdevice/productname/getdata")
                resp = self._post({"code": "request", "cid": -1, "adr": adr})
                if resp and resp.get('code') == 200:
                    found = resp['data']['value']
                    if found != expected and expected != 'generic':
                        self.log.warn(f"Port {port}: expected {expected}, "
                                      f"found {found}")
                    else:
                        self.log.info(f"Port {port}: {found}")
                elif resp and resp.get('code') == 503:
                    self.log.error(f"Port {port}: no IO-Link device connected")
                else:
                    self.log.warn(f"Port {port}: unexpected response {resp}")

            self.initialized = True

        if params.get('auto_acquire', False):
            self.agent.start('acq')

        return True, f"Initialized {self.device_model} with " \
                     f"{len(self.ports_config)} port(s)"

    @ocs_agent.param('sample_freq', default=1.0, type=float)
    @ocs_agent.param('quantize', default=True, type=bool)
    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """acq(sample_freq=1.0, quantize=True, test_mode=False)

        **Process** - Acquire data from all configured IO-Link ports.

        Reads all ports in a single HTTP request using the getdatamulti
        service, then decodes each port's process data according to its
        configured sensor type.

        Parameters
        ----------
        sample_freq : float, optional
            Sampling frequency in Hz. Default is 1.0.
        quantize : bool, optional
            If True, align samples to time grid. Default is True.
        test_mode : bool, optional
            Exit after one iteration. Default is False.

        Notes
        -----
        The most recent data collected is stored in session data::

            >>> response.session['data']
            {'timestamp': 1682630863.0,
             'fields': {'port1_flow': 42.4,
                        'port1_temperature': 22.8,
                        'port2_level': 85.0,
                        'port2_status': 0}}

        """
        pm = Pacemaker(params['sample_freq'], quantize=params['quantize'])
        self.take_data = True

        datatosend = [
            f"/iolinkmaster/port[{pc['port']}]/iolinkdevice/pdin"
            for pc in self.ports_config
        ]

        while self.take_data:
            pm.sleep()

            if not self.initialized:
                self.log.warn("Not initialized, waiting...")
                time.sleep(5)
                continue

            payload = {
                "code": "request",
                "cid": -1,
                "adr": "getdatamulti",
                "data": {"datatosend": datatosend}
            }

            resp = self._post(payload)

            if resp is None:
                self.log.error("No response from device, marking "
                               "uninitialized")
                self.initialized = False
                continue

            if resp.get('code') != 200:
                self.log.warn(f"Device returned code {resp.get('code')}")
                continue

            now = time.time()
            fields = {}

            for i, pc in enumerate(self.ports_config):
                port_key = datatosend[i]
                port_resp = resp.get('data', {}).get(port_key)
                if port_resp is None:
                    self.log.warn(f"No data for port {pc['port']}")
                    continue
                if port_resp.get('code') != 200:
                    self.log.warn(f"Port {pc['port']} returned code "
                                  f"{port_resp.get('code')}")
                    continue

                raw_value = port_resp.get('data')
                if raw_value is None:
                    continue

                extractor = SENSOR_EXTRACTORS.get(
                    pc['sensor_type'], extract_generic)
                extracted = extractor(raw_value)

                for key, val in extracted.items():
                    fields[f"port{pc['port']}_{key}"] = val

            if fields:
                data = {'block_name': 'sensors',
                        'timestamp': now,
                        'data': fields}
                self.agent.publish_to_feed('iolink_sensors', data)

            session.data = {'timestamp': now, 'fields': fields}

            if params['test_mode']:
                break

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """Stop the acq process."""
        self.take_data = False
        return True, 'Stopping acquisition'


def parse_port_arg(port_str):
    """Parse a port argument like '1:SBN246' into a config dict."""
    parts = port_str.split(':', 1)
    if len(parts) != 2:
        raise argparse.ArgumentTypeError(
            f"Port must be 'PORT_NUM:SENSOR_TYPE', got '{port_str}'")
    try:
        port_num = int(parts[0])
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Port number must be an integer, got '{parts[0]}'")
    sensor_type = parts[1]
    return {'port': port_num, 'sensor_type': sensor_type}


def make_parser(parser=None):
    """Build the argument parser for the Agent.

    Allows sphinx to automatically build documentation based on this
    function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address', type=str, required=True,
                        help="IP address of the IO-Link master (IoT port).")
    pgroup.add_argument('--port', type=parse_port_arg, action='append',
                        dest='ports', metavar='PORT:SENSOR_TYPE',
                        help="Port config as 'PORT_NUM:SENSOR_TYPE'. "
                             "Repeat for each port. "
                             "Example: --port 1:SBN246 --port 2:KQ1001")
    pgroup.add_argument('--sample-freq', type=float, default=1.0,
                        help="Sampling frequency in Hz. Default 1.0.")
    pgroup.add_argument('--quantize', action='store_true', default=True,
                        help="Align samples to time grid.")
    pgroup.add_argument('--mode', type=str, default='acq',
                        choices=['init', 'acq'],
                        help="Startup mode. 'acq' auto-starts acquisition.")

    return parser


def main(args=None):
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='IFMIOLinkMasterAgent',
                                  parser=parser,
                                  args=args)

    if not args.ports:
        raise ValueError("At least one --port argument is required. "
                         "Example: --port 1:SBN246")

    init_params = False
    if args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)
    master = IFMIOLinkMasterAgent(agent, args.ip_address, args.ports)

    agent.register_task('init_iolink_master', master.init_iolink_master,
                        startup=init_params)
    agent.register_process('acq', master.acq, master._stop_acq)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
