import txaio
from pyModbusTCP.client import ModbusClient

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# TODO: need driver code that knows which register address info to grab 
# based on port you attach things to

# dictionary for defining register address given the port you plug into
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
    ip: str
        IP address of the power meter
    port : int
        Port for the ip address
    daq_port: string
        port on daq IO device that plugs into the IFM devices
    unit_id : int
        # TODO: idk yet
    auto_open : bool
        # TODO
    auto_close : bool
        # TODO
    """
    def __init__(self, agent, ip_address, daq_port, port=502, unit_id=1, auto_open=True, auto_close=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

         # TODO: fix the order

        self.ip_address = ip_address
        self.port = port
        self.daq_port = daq_port
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
        """acq()
        **Process** - Fetch values from the Elnet Power Meter
        Parameters
        ----------
        test_mode : bool, option
            Run the Process loop only once. Meant only for testing.
            Default is False.
        """
        self.take_data = True
        while self.take_data:
            m = ModbusClient(host=self.ip_address, port=self.port, unit_id=self.unit_id, auto_open=self.auto_open, auto_close=self.auto_close)
           
            # and then you need to split it into a float value; i think this should all be done as driver code above the class
            register = int(daq_ports[self.daq_port])
            print('register1', register)
            register_temp = register + 1
            register_temp = int(register_temp)
            print('register_temp', register_temp)

            
            flow = m.read_holding_registers(register, 1)
            temp = m.read_holding_registers(register_temp, 1)

            data = {'block_name': 'flowmeter',
                    'timestamp': time.time(),
                    'data' :{'flow': flow}},
                            # 'temp': temp}
                   # }

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
    pgroup.add_argument("--auto-close", type=bool, default=False, help="state for automatically closing TCP connection")


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='FlowmeterAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    flowmeter = FlowmeterAgent(agent, args.ip_address, args.daq_port, args.port, args.unit_id, args.auto_open, args.auto_close)

    agent.register_process('acq', flowmeter.acq, flowmeter._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)

if __name__ == "__main__":
    main()
