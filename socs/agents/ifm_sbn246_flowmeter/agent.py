import txaio
import time

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock, Pacemaker

on_rtd = environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from pyModbusTCP.client import ModbusClient


# dictionary for defining register address given the daq port you plug into
daq_ports = {1: 1002,
             2: 2002,
             3: 3002,
             4: 4002}


class FlowmeterAgent:
    """Monitor the flowmeter.

    Parameters
    ----------
    agent : OCS Agent
        OCSAgent object which forms this Agent
    ip_address: str
        IP address of IFM DAQ IO device
    port : int
        Port for the ip address. Default is 502 for the DAQ device
    daq_port: int
        Port on daq IO device that connects to flowmeter
    unit_id : int
        Unit identifier for Modbus bridge that allows for communication
        across multiple ports on the daq device while using the same
        ip address. Default unit identifier is 1
    auto_open : bool
        State for automatically keeping TCP connection open
    auto_close : bool
        State for automatically closing TCP connection
    """
    def __init__(self, agent, ip_address, daq_port, port=502, unit_id=1, auto_open=True, auto_close=True):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.port = port
        self.daq_port = daq_port
        self.unit_id = unit_id
        self.auto_open = auto_open
        self.auto_close = auto_close

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
        """acq(test_mode=False)

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
            m = ModbusClient(host=self.ip_address, port=self.port, unit_id=self.unit_id, auto_open=self.auto_open, auto_close=self.auto_close)

            register = int(daq_ports[self.daq_port])
            sensor_data = m.read_holding_registers(register, 2)
            flow = sensor_data[0]  # gallons/min
            temp = sensor_data[1]  # Celsius

            # convert flow and temp into floats
            flow = flow / 10
            temp = temp / 10

            data = {'block_name': 'flowmeter',
                    'timestamp': time.time(),
                    'data': {'flow': flow,
                             'temp': temp}
                    }

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
    pgroup.add_argument("--ip-address", type=str, default='localhost', help="ip address of IFM DAQ IO device connected to IFM flowmeter")
    pgroup.add_argument("--daq-port", type=int, default=1, help="Port number on IFM DAQ IO device that IFM is connected to")
    pgroup.add_argument("--port", type=int, default=5021, help="PyModbusTCP port for querying information from the DAQ Modbus TCP port")
    pgroup.add_argument("--unit-id", type=int, default=1, help="Unit ID for pymodbus TCP protocol")
    pgroup.add_argument("--auto-open", type=bool, default=True, help="state for automatically keeping TCP connection open")
    pgroup.add_argument("--auto-close", type=bool, default=True, help="state for automatically closing TCP connection")

    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='FlowmeterAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    f = FlowmeterAgent(agent, args.ip_address, args.daq_port, args.port, args.unit_id, args.auto_open, args.auto_close)

    agent.register_process('acq', f.acq, f._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
