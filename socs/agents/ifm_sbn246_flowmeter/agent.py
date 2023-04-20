import txaio
from pyModbusTCP.client import ModbusClient

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# TODO: need driver code that knows which register address info to grab 
# based on port you attach things to

# dictionary for defining register address given the port you plug into
daq_ports = {'X01': 1002,
             'X02': 2002,
             'X03': 3002,
             'X04': 4002}


class SBNFlowmeterAgent:
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
    def __init__(self, agent, ip, daq_port, port=502, unit_id=1, auto_open=True, auto_close=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port
        self.daq_port = daq_port
        self.auto_open = auto_open
        self.auto_close = auto_close

        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('powermeter',
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
            m = ModbusClient(host=self.ip, port=self.port, unit_id=self.unit_id, auto_open=self.auto_open, auto_close=self.auto_close)
           
            register = daq_ports[daq_port] # TODO: this is wrong because you need both 1002, and 1003 register address to read the flow and temp
                                           # so find a smarter way to do this
                                           # and then you need to split it into a float value; i think this should all be done as driver code above the class
            
            flow = m.read_holding_registers(register, 1)
            temp = m.read_holding_registers(register, 1)

            data = {'block_name': 'flowmeter',
                    'timestamp': time.time(),
                    'data' :{'flow': flow,
                             'temp': temp}
                    }

            self.agent.publish_to_feed('powermeter_status', data)

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
        parser_in - A()
    pgroup = praser_in.add_argument_group('Agent Options')
    pgroup.add_argument("--ip-address", type=str, help="ip address of IFM DAQ IO device connected to IFM flowmeter")
    pgroup.add_argument("--daq-port", type=int, help="Port number on IFM DAQ IO device that IFM is connected to")
    pgroup.add_argument("--port", type=int, default=502, help="PyModbusTCP port for querying information from the DAQ Modbus TCP port")
    pgroup.add_argument("--unit-id", type=int, default=1, help="Unit ID for pymodbus TCP protocol")
    pgroup.add_argument("--auto-open", type=bool, default=True, help="state for automatically keeping TCP connection open")
    pgroup.add_argument("--auto-close", type=bool, default=False, help="state for automatically closing TCP connection")


def main():
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='SBNFlowmeterAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    flowmeter = SBNFlowmeterAgent(agent, args.ip, args.daq_port, args.port, args.unit_id, args.auto_open, args.auto_close)

    agent.register_process('acq', flowmeter.acq, flowmeter._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)

if __name__ == "__main__":
    main()
