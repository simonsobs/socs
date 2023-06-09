import txaio
import argparse
import time
from pyModbusTCP.client import ModbusClient

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

powermeter_keys = {'volt1': 1,
                   'volt2': 3,
                   'volt3': 5,
                   'amps1': 13,
                   'amps2': 15,
                   'amps3': 17,
                   'freq1': 51,
                   'freq2': 53,
                   'freq3': 55,
                   'total_active_power': 25}

class ElnetPowermeterAgent:
    """Monitor the Power Meter.

    Parameters
    ----------
    agent : OCS Agent
        OCSAgent object which forms this Agent
    ip: str
        IP address of the power meter
    port : int
        Port for the ip address
    unit_id : int
        # TODO: idk yet
    auto_open : bool
        # TODO
    auto_close : bool
        # TODO
    """
    def __init__(self, agent, ip, port, unit_id=1, auto_open=True, auto_close=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port
        self.unit_id = unit_id
        self.auto_open = auto_open
        self.auto_close = auto_close
        self.initialized = False

        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('powermeter',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

    @ocs_agent.param('auto_acquire', default=False, type=bool)
    def init_powermeter(self, session, params=None):
        """init_powermeter(auto_acquire=False)
        
        **Task** - Perform first time setup of the Elnet Powermeter

        Parameters
        ----------
        auto_acquire : bool, option
            Starts data acquistion after initialization if True. 
            Defaults to False.

        """
        # TODO: check this parms is none, don't need this
        if params is None:
            params = {}

        auto_acquire = params.get('auto_acquire', False)

        if self.initialized:
            return True, "Already initialized."
        
        # TODO: check the timeout order of this
        with self.lock.acquire_timeout(3, job='init_powermeter') as acquired:
            if not acquired:
                self.log.warn("Could not start init because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('starting')

            c = ModbusClient(self.ip, port=self.port, auto_open=self.auto_open, auto_close=self.auto_close)
            if c.open():
                self.client = c # TODO this necessary somewhere else? 
                self.initialized = True
            else:
                self.initialized = False
                return False, "Could not connect to power meter"

        # Start acq if requested
        if auto_acquire:
            self.agent.start('acq')

        return True, "Power meter initialized."

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """acq(test_mode=False)

        **Process** - Fetch values from the Elnet Power Meter

        Parameters
        ----------
        test_mode : bool, option
            Run the Process loop only once. Meant only for testing.
            Default is False.

        """
        if params is None:
            params = {}

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running"
                              .format(self.lock.job))
                return False, "Could not acquire lock."
            
            session.set_status('running')

            self.take_data = True
            while self.take_data:
                m = ModbusClient(self.ip, port=self.port, unit_id=self.unit_id, auto_open=self.auto_open, auto_close=self.auto_close)

                data = {'block_name': 'powermeter',
                        'timestamp': time.time(),
                        'data' :{'fields': {}}}

                data_cache = {'timestamp': time.time(),
                              'fields': {}}
                
                for key in powermeter_keys:
                    val = m.read_holding_registers(powermeter_keys[key],1)
                    val = int(val[0])
                    info = {key: val}
                    data['data']['fields'].update(info)
                    data_cache['fields'].update(info)

                self.agent.publish_to_feed('powermeter', data)
                
                session.data.update(data_cache)
                
                if params['test_mode']:
                    break

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        self.take_data = False
        return True, 'Stopping acq process'


def make_parser(parser=None):
    if parser is None:
        parser=argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument("--ip", type=str, help="IP Address to listen to.")
    pgroup.add_argument("--port", type=int, default=502, help="Port to listen on.")
    pgroup.add_argument("--mode", type=str, choices=['idle', 'init', 'acq'],
                       help="Starting action for the agent.")

    return parser

def main(args=None):
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    args = site_config.parse_args(agent_class='ElnetPowermeterAgent',
                                  parser=parser,
                                  args=args)

    # Automatically acquire data if requested
    init_params = False
    if args.mode == 'init':
        init_params = {'auto_acquire': False}
    elif args.mode == 'acq':
        init_params = {'auto_acquire': True}

    agent, runner = ocs_agent.init_site_agent(args)

    p = ElnetPowermeterAgent(agent,
                             ip=args.ip,
                             port=int(args.port))

    agent.register_task('init_powermeter', p.init_powermeter,
                        startup=init_params)
    agent.register_process('acq', p.acq, p._stop_acq)

    runner.run(agent, auto_reconnect=True)

if __name__ == '__main__':
    main()
