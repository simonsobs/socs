import argparse
import time
from os import environ

import requests
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock


def extract(value):
    """
    Extract flow and temp from raw hexidecimal value from SBN246 Process Data.

    Parameters
    ----------
    value : str
        Hexidecimal value from SBN246 Process Data.

    Returns
    -------
    float, int
        The flow in units of gallons per minute (gpm) and temperature in units
        of F.

    """
    binary = bin(int(value, 16))[2:].zfill(32)
    _b_flow = binary[0:16]
    _b_temp = binary[16:30]

    flow = int(_b_flow, 2) / 10
    temp = int(_b_temp, 2)

    return flow, temp


class FlowmeterAgent:
    """
    Monitor the flowmeter.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent.
    ip_address: str
        IP address of IO-Link master to make requests from.
    daq_port: int
        Port on IO-Link master that connects to flowmeter. Choices are 1-4.

    """

    def __init__(self, agent, ip_address, daq_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.daq_port = daq_port

        # check serial number of flowmeter, otherwise may seriously
        # impact understanding of our flow and temp (converted into metric)
        prod_adr = "/iolinkmaster/port[{}]/iolinkdevice/productname/getdata".format(self.daq_port)
        q = requests.post('http://{}'.format(self.ip_address), json={"code": "request", "cid": -1, "adr": prod_adr})
        assert q.json()['data']['value'] == 'SBN246', "Flowmeter device is not an SBN246 model"

        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('flowmeter',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """
        acq(test_mode=False)

        **Process** - Fetch values from the flowmeter using the IO-Link master.

        Parameters
        ----------
        test_mode : bool, optional
            Run the Process loop only once. Meant only for testing.
            Default is False.

        Notes
        -----
        The most recent data collected is stored in session data in the
        following structure. Note the units are [liters/min] and [Celsius]::

            >>> response.session['data']
            {'timestamp': 1682630863.0066128,
             'fields':
                {'flow': 42.4, 'temperature': 22.8}
            }

        """
        pm = Pacemaker(1, quantize=True)
        self.take_data = True

        while self.take_data:
            pm.sleep()

            dp = int(self.daq_port)
            adr = "/iolinkmaster/port[{}]/iolinkdevice/pdin/getdata".format(dp)
            url = 'http://{}'.format(self.ip_address)

            try:
                r = requests.post(url, json={"code": "request", "cid": -1, "adr": adr})
            except requests.exceptions.ConnectionError as e:
                self.log.warn(f"Connection error occured: {e}")
                continue

            value = r.json()['data']['value']

            flow_gpm, temp_f = extract(value)  # units [gallons/minute], [F]
            flow = flow_gpm * 3.785411784  # liters/minute
            flow = round(flow, 1)
            temp = (temp_f - 32) * (5 / 9)  # Celsius
            temp = round(temp, 1)
            now = time.time()

            data = {'block_name': 'flowmeter',
                    'timestamp': now,
                    'data': {'flow': flow,
                             'temperature': temp}
                    }

            self.agent.publish_to_feed('flowmeter', data)

            session.data = {"timestamp": now,
                            "fields": {}}

            session.data['fields']['flow'] = flow
            session.data['fields']['temperature'] = temp

            if params['test_mode']:
                break

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        self.take_data = False

        return True, 'Stopping acq process'


def add_agent_args(parser_in=None):
    if parser_in is None:
        parser_in = argparse.ArgumentParser()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--ip-address", type=str, help="IP address of IO-Link master.")
    pgroup.add_argument("--daq-port", type=int, help="Port on IO-Link master that flowmeter is connected to.")

    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='FlowmeterAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    f = FlowmeterAgent(agent, args.ip_address, args.daq_port)

    agent.register_process('acq', f.acq, f._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
