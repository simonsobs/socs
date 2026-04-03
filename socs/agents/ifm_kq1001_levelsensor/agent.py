import argparse
import time
from os import environ

import requests
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock


def extract(value):
    """
    Extract level and device status from raw hexidecimal value from
    KQ1001 Process Data.

    Parameters
    ----------
    value : str
        Hexidecimal value from KQ1001 Process Data.

    Returns
    -------
    float, int
        The level in % and the device status.

    """
    binary = bin(int(value, 16))[2:].zfill(32)
    # Decode all of the process data fields, but most of them don't
    # matter.
    _b_pdv1 = binary[0:16]
    # _b_scale_levl = binary[16:24]
    _b_device_status = binary[24:28]
    # _b_out3 = binary[29:30]
    # _b_out2 = binary[30:31]
    # _b_out1 = binary[31:32]

    pdv1 = int(_b_pdv1, 2) * 1.0
    device_status = int(_b_device_status, 2)

    return pdv1, device_status


class LevelSensorAgent:
    """
    Monitor the level sensor.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent.
    ip_address: str
        IP address of IO-Link master to make requests from.
    daq_port: int
        Port on IO-Link master that connects to level sensor. Choices are 1-4.

    """

    def __init__(self, agent, ip_address, daq_port):
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.ip_address = ip_address
        self.daq_port = daq_port

        # check make of the level sensor, otherwise data may make no
        # sense
        prod_adr = "/iolinkmaster/port[{}]/iolinkdevice/productname/getdata".format(self.daq_port)
        q = requests.post('http://{}'.format(self.ip_address), json={"code": "request", "cid": -1, "adr": prod_adr})
        assert q.json()['data']['value'] == 'KQ1001', "Device is not an KQ1001 model level sensor.  Give up!"

        self.take_data = False

        agg_params = {'frame_length': 60,
                      'exclude_influx': False}

        # register the feed
        self.agent.register_feed('levelsensor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1
                                 )

    @ocs_agent.param('test_mode', default=False, type=bool)
    def acq(self, session, params=None):
        """
        acq(test_mode=False)

        **Process** - Fetch values from the level sensor using the
          IO-Link master.

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
                {'level': 82.0, 'status': 0}
            }

        """
        pm = Pacemaker(0.2, quantize=False)
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

            now = time.time()
            value = r.json()['data']['value']

            level_pct, status_int = extract(value)  # units [gallons/minute], [F]

            data = {'block_name': 'levelsensor',
                    'timestamp': now,
                    'data': {'level': level_pct,
                             'status': status_int}
                    }

            self.agent.publish_to_feed('levelsensor', data)

            session.data = {"timestamp": now,
                            "fields": {}}

            session.data['fields']['level'] = level_pct
            session.data['fields']['status'] = status_int

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
    pgroup.add_argument("--daq-port", type=int, help="Port on IO-Link master that level sensor is connected to.")

    return parser_in


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='LevelSensorAgent', parser=parser, args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    f = LevelSensorAgent(agent, args.ip_address, args.daq_port)

    agent.register_process('acq', f.acq, f._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
