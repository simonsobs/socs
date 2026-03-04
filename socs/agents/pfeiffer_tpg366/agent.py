# Script to log and readout pfeiffer TPG 366 gauge contoller
# via Ethernet connection
# Zhilei Xu, Tanay Bhandarkar

import argparse
import os
import socket
import time

import numpy as np
import txaio
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# For logging
txaio.use_twisted()

BUFF_SIZE = 128
ENQ = '\x05'


class Pfeiffer:
    """CLASS to control and retrieve data from the pfeiffer tpg366
    pressure gauge controller


    Args:
        ip_address: IP address of the deivce
        porti (int): 8000 (fixed for the device)

    Attributes:
       read_pressure reads the pressure from one channel (given as an argument)
       read_pressure_all reads pressures from the six channels
       close closes the socket
    """

    def __init__(self, ip_address, port, timeout=10,
                 f_sample=1.):
        self.ip_address = ip_address
        self.port = port
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
        self.log = txaio.make_logger()

    def channel_power(self):
        """
        Function to check the power status of all channels.

        Args:
            None

        Returns:
            List of channel states.

        """
        msg = 'SEN\r\n'
        self.comm.send(msg.encode())
        self.comm.recv(BUFF_SIZE).decode()
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        power_str = read_str.split('\r')
        power_states = np.array(power_str[0].split(','), dtype=int)
        if any(chan == 1 for chan in power_states):
            channel_states = [index + 1 for index, state in enumerate(power_states) if state == 1]
            self.log.debug("The following channels are off: {}".format(channel_states))
        return channel_states

    def read_pressure(self, ch_no):
        """
        Function to measure the pressure of one given channel
        ch_no is the chanel to be measured (e.g. 1-6)
        returns the measured pressure as a float

        Args:
            ch_no: The channel to be measured (1-6)

        Returns:
            pressure as a float
        """
        msg = 'PR%d\r\n' % ch_no
        self.comm.send(msg.encode())
        self.comm.recv(BUFF_SIZE).decode()
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        pressure_str = read_str.split(',')[-1].split('\r')[0]
        pressure = float(pressure_str)
        return pressure

    def read_pressure_all(self):
        """measure the pressure of all channel
        Return an array of 6 pressure values as a float array

        Args:
            None

        Returns:
            6 element array corresponding to each channels
            pressure reading, as floats
        """
        msg = 'PRX\r\n'
        self.comm.send(msg.encode())
        # Could use this to catch exemptions, for troubleshooting
        self.comm.recv(BUFF_SIZE).decode()
        self.comm.send(ENQ.encode())
        read_str = self.comm.recv(BUFF_SIZE).decode()
        pressure_str = read_str.split('\r')[0]
        gauge_states = pressure_str.split(',')[::2]
        gauge_states = np.array(gauge_states, dtype=int)
        pressures = pressure_str.split(',')[1::2]
        pressures = [float(p) for p in pressures]
        if any(state != 0 for state in gauge_states):
            index = np.where(gauge_states != 0)
            for j in index[0]:
                pressures[j] = 0.
        return pressures

    def close(self):
        """Close the socket of the connection"""
        self.comm.close()


class PfeifferAgent:

    def __init__(self, agent, ip_address, port, f_sample=1.):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.f_sample = f_sample
        self.take_data = False
        self.gauge = Pfeiffer(ip_address, int(port))
        agg_params = {'frame_length': 60, }
        self.agent.register_feed('pressures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @ocs_agent.param('sampling_frequency', type=float, default=2.5)
    @ocs_agent.param('test_mode', type=bool, default=False)
    def acq(self, session, params=None):
        """acq(sampling_frequency=2.5, test_mode=False)

        **Process** - Get pressures from the Pfeiffer gauges.

        Parameters:
            sampling_frequency (float): Rate at which to get the pressures
                [Hz]. Defaults to 2.5 Hz.
            test_mode (bool): Run the Process loop only once. This is meant
                only for testing. Defaults to False.

        """
        f_sample = params['sampling_frequency']
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1. / f_sample - 0.01

        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            self.take_data = True
            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'pressures',
                    'data': {}
                }
                # Useful for debugging, but should separate to a task to cut
                # down on queries in the main acq() loop.
                # self.gauge.channel_power()
                pressure_array = self.gauge.read_pressure_all()
                # Loop through all the channels on the device
                for channel in range(len(pressure_array)):
                    data['data']["pressure_ch" + str(channel + 1)] = pressure_array[channel]

                self.agent.publish_to_feed('pressures', data)
                time.sleep(sleep_time)

                if params['test_mode']:
                    break

            self.agent.feeds['pressures'].flush_buffer()
        return True, 'Acquistion exited cleanly'

    def _stop_acq(self, session, params=None):
        """
        End pressure data acquisition
        """
        if self.take_data:
            self.take_data = False
            self.gauge.close()
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip_address')
    pgroup.add_argument('--port')
    pgroup.add_argument("--mode", type=str, default='acq', choices=['acq', 'test'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()
    args = site_config.parse_args(agent_class='PfeifferAgent',
                                  parser=parser,
                                  args=args)

    init_params = True
    if args.mode == 'test':
        init_params = {'test_mode': True}

    agent, runner = ocs_agent.init_site_agent(args)
    pfeiffer_agent = PfeifferAgent(agent, args.ip_address, args.port)
    agent.register_process('acq', pfeiffer_agent.acq,
                           pfeiffer_agent._stop_acq, startup=init_params)
    agent.register_task('close', pfeiffer_agent._stop_acq)
    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
