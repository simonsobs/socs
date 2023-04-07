import txaio
from pyModbusTCP.client import ModbusClient

from os import environ
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

class ElnetPowerMeterAgent:
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
    def __init__(self, agent, ip, port=502, unit_id=1, auto_open=True, auto_close=False):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip = ip
        self.port = port
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
           
            # TODO: possibly still care about the voltage between the lines and the power factor between the lines
            volt1 = m.read_holding_registers(1,2)
            volt2 = m.read_holding_registers(3,2)
            volt3 = m.read_holding_registers(5,2)

            current1 = m.read_holding_registers(13,2)
            current2 = m.read_holding_registers(15,2)
            current3 = m.read_holding_registers(17,2)
            
            power_fac1 = m.read_holding_registers(43,2)  # this is PF, there's also an L&C and idk what those mean
            power_fac2 = m.read_holding_registers(45,2)
            power_fac3 = m.read_holding_registers(47,2)

            total_powerfac = m.read_holding_registers(49,2)
            
            freq1 = m.read_holding_registers(51,2)
            freq2 = m.read_holding_registers(53,2)
            freq3 = m.read_holding_registers(55,2)

            data = {'block_name': 'powermeter_status',
                    'timestamp': time.time(),
                    'data' :{}}

            data['data']['voltage_line1'] = volt1
            data['data']['voltage_line2'] = volt2
            data['data']['voltage_line3'] = volt3
            data['data']['current_line1'] = current1
            data['data']['current_line2'] = current2
            data['data']['current_line3'] = current3
            data['data']['powerfactor_line1'] = power_fac1
            data['data']['powerfactor_line2'] = power_fac2
            data['data']['powerfactor_line3'] = power_fac3
            data['data']['frequency_line1'] = freq1
            data['data']['frequency_line2'] = freq2
            data['data']['frequency_line3'] = freq3
            data['data']['total_powerfactor'] = total_powerfac

            self.agent.publish_to_feed('powermeter_status', data)

            if params['test_mode']:
                break

        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        self.take_data = False
        return True, 'Stopping acq process''
