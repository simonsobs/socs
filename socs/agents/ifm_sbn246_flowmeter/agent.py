import time
from os import environ
import requests

import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

# TODO: fix below, not sure we need the on_rtd since we already have the requests package
#on_rtd = environ.get('READTHEDOCS') == 'True'
#if not on_rtd:
#    from pyModbusTCP.client import ModbusClient


def extract(value):
    """
    Extract flow and temp from raw hexidecimal value from SBN246 Process Data.

    Args:
        value (str): Hexidecimal value from SBN246 Process Data.

    Returns:
        float, int: The flow in units of gallons per minute (gpm) and
        temperature in units of F.

    """
    binary = bin(int(value, 16))[2:].zfill(32)
    _b_flow = binary[0:16]
    _b_temp = binary[17:30]

    flow = int(_b_flow, 2) / 10
    temp = int(_b_temp, 2)

    return flow, temp


class FlowmeterAgent:
    """
    Monitor the flowmeter.

    Parameters
    ----------
    agent : OCS Agent
        OCSAgent object which forms this Agent
    url: str
        HTTP url of the DAQ IO-Link device to make requests from
        Ex: 'http://10.10.10.159'
    daq_port: int
        Port on daq IO device that connects to flowmeter. Choices are 1-4
    """

    def __init__(self, agent, url, daq_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.url = url
        self.daq_port = daq_port

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

        **Process** - Fetch values from the flowmeter using the DAQ device

        Parameters
        ----------
        test_mode : bool, option
            Run the Process loop only once. Meant only for testing.
            Default is False.
        """
        pm = Pacemaker(1, quantize=True)
        self.take_data = True
        while self.take_data:
            pm.sleep()

            dp = int(self.daq_port)
            adr = "/iolinkmaster/port[{}]/iolinkdevice/pdin/getdata".format(dp)

            r = requests.post(self.url, json={"code": "request", "cid": -1, "adr": adr})
            value = r.json()['data']['value']

            flow, temp = extract(value)

            data = {'block_name': 'flowmeter',
                    'timestamp': time.time(),
                    'data': {'flow': flow,
                             'temp': temp}
                    }

            print(data)

            self.agent.publish_to_feed('flowmeter', data)

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
        from argparse import ArgumentParser as A
        parser_in = A()
    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--url", type=str, help="HTTP address of DAQ IO-Link device. Ex: 'http://10.10.10.159'")
    pgroup.add_argument("--daq-port", type=int, help="Port on DAQ IO-Link device that IFM is connected to")

    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='FlowmeterAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    f = FlowmeterAgent(agent, args.url, args.daq_port)

    agent.register_process('acq', f.acq, f._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
