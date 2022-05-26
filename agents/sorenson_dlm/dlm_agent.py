# Script to log and control the Sorenson DLM power supply, for heaters
# Tanay Bhandarkar, Jack Orlowski-Scherer
import time
import socket
import argparse
from ocs import site_config, ocs_agent
from ocs.ocs_twisted import TimeoutLock, Pacemaker


class DLM:
    def __init__(self, ip_address, port=9221, timeout=10):
        self.ip_address = ip_address
        self.port = port
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)

    def send_msg(self, cmd):
        """
        Sends a message to the DLM. 'OPC?' causes the DLM to wait for the
        previous command to complete to being the next
        """
        msg = str(cmd) + ';OPC?\r\n'
        self.comm.send(msg.encode('ASCII'))

    def rec_msg(self):
        """
        Waits for a message from the DLM, typically as a result of a query,
        and returns it
        """
        dataStr = self.comm.recv(1024).decode('ASCII')
        return dataStr.strip()

    def set_overv_prot(self, voltage):
        """
        Sets the overvoltage protection
        """
        self.send_msg('*CLS')
        self.send_msg('*RST')
        self.send_msg('SOUR:VOLT:PROT {}'.format(voltage))

        self.send_msg('SOUR:VOLT:PROT?')
        ovp = self.rec_msg()
        if ovp != voltage:
            print("Error: Over voltage protection not set to requested value")
            return

        self.send_msg('STAT:PROT:ENABLE 8')
        self.send_msg('STAT:PROT:ENABLE?')
        enb = self.rec_msg()
        if enb != '8':
            print('Error: Over voltage protection failed to enable')
            return

        self.send_msg('STAT:PROT:EVENT?')
        event = self.rec_msg()
        if event != '0':
            print('Error: Over voltage already tripped')
            return

    def read_voltage(self):
        """
        Reads output  voltage
        """
        self.send_msg('SOUR:VOLT?')
        msg = self.rec_msg()
        return msg

    def read_current(self):
        """
        Reads output current
        """
        self.send_msg('MEAS:CURR?')
        msg = self.rec_msg()
        return msg

    def sys_err_check(self):
        """
        Queries sytem error and returns error byte
        """
        self.send_msg('SYST:ERR?')
        msg = self.rec_msg()
        return msg


class DLMAgent:
    """ Agent to connect to a Sorenson DLM power supply via ethernet.

    Args:
        ip_address: str
            IP address of the DLM
        port: int
            Port number for DLM; default is 9221

    """

    def __init__(self, agent, ip_address, port, f_sample=2.5):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.f_sample = f_sample
        self.take_data = False
        self.over_volt = 0.

        try:
            self.dlm = DLM(ip_address, int(port))
        except socket.timeout as e:
            self.log.error("DLM power supply has timed out"
                           + f"during connect with error {e}")
            return False, "Timeout"

        agg_params = {'frame length': 60, }
        self.agent.register_feed('voltages',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def acq(self, session, params=None):
        """acq("wait=1, test_mode=False)
        Get voltage and current values from the sorenson, publishes them to
        the feed

        Args:
            sampling_frequency: float
                defaults to 2.5Hz
        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency')
        if f_sample is None:
            f_sample = self.f_sample
        if f_sample % 1 == 0:
            pm = Pacemaker(f_sample, True)
        else:
            pm = Pacemaker(f_sample)
        wait_time = 1 / f_sample
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            pm.sleep()
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')
            last_release = time.time()
            self.take_data = True

            while self.take_data:
                # About every second, release and acquire the lock
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        print(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False
                data = {
                    'timestamp': time.time(),
                    'block_name': 'voltages',
                    'data': {}
                }
                voltage_reading = self.dlm.read_voltage()
                current_reading = self.dlm.read_current()
                self.log.debug('Voltage: {}'.format(voltage_reading))
                self.log.debug('Current: {}'.format(current_reading))

                data['data']["voltage"] = float(voltage_reading)
                data['data']["current"] = float(current_reading)

                self.agent.publish_to_feed('voltages', data)
                time.sleep(wait_time)

            self.agent.feeds['voltages'].flush_buffer()
        return True, 'Acquistion exited cleanly'

    @ocs_agent.param('voltage', default=0., type=float, check=lambda V: 0 <= V <= 300)
    def set_voltage(self, session, params=None):
        """set_voltage(voltage=None)

        Sets voltage of power supply:
        Args:
            voltage (float): Voltage to set.

        Examples::
            Example of a client, setting the current to 1V:

                client.set_voltage(voltage = 1.)

        """

        with self.lock.acquire_timeout(timeout=3, job='init') as acquired:
            if acquired:
                if self.over_volt == 0:
                    return False, 'Over voltage protection not set'
                elif float(params['voltage']) > float(self.over_volt):
                    return False, 'Voltage greater then over voltage protection'
                else:
                    self.dlm.send_msg('SOUR:VOLT {}'.format(params['voltage']))
            else:
                return False, "Could not acquire lock"

        return True, 'Set voltage to {}'.format(params['voltage'])

    def set_over_volt(self, session, params=None):
        """set_over_volt(over_volt=None)

        Sets over voltage protection of power supply.

        Args:
            over_volt (int): Over voltage protection to set

        Examples::
            Example of a client, setting the overvoltage protection to 10V:

                client.set_over_volt(over_volt = 10.)

        """

        with self.lock.acquire_timeout(timeout=3, job='init') as acquired:
            if acquired:
                self.dlm.set_overv_prot(params['over_volt'])
                self.over_volt = float(params['over_volt'])
            else:
                return False, 'Could not acquire lock'
        return True, 'Set over voltage protection to {}'.format(params['over_volt'])

    @ocs_agent.param('current', default=0., type=float, check=lambda I: 0 <= I <= 2)
    def set_current(self, session, params=None):
        """set_current(current=None)

        Sets current of power supply:
        Args:
            current (float): Current to set.

        Examples::
            Example of a client, setting the current to 1A:

                client.set_current(current = 1.)

        """

        with self.lock.acquire_timeout(timeout=3, job='init') as acquired:
            if acquired:
                if self.over_volt == 0:
                    return False, 'Over voltage protection not set'
                elif float(params['voltage']) > float(self.over_volt):
                    return False, 'Voltage greater then over voltage protection'
                else:
                    self.dlm.send_msg('SOUR:CURR {}'.format(params['current']))
            else:
                return False, "Could not acquire lock"

        return True, 'Set current to {}'.format(params['current'])

    def _stop_acq(self, session, params=None):
        """
        End voltage data acquisition
        """
        if self.take_data:
            self.take_data = False
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
    pgroup.add_argument('--ip-address', type=str, help="Serial-to-ethernet "
                        + "converter ip address")
    pgroup.add_argument('--port-number', type=int, help="Serial-to-ethernet "
                        + "converter port")
    pgroup.add_argument('--mode', type=str, help="Set to acq to run acq on "
                        + "startup")

    return parser


if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip_address')
    pgroup.add_argument('--port')
    pgroup.add_argument('--voltage')

    args = parser.parse_args()

    site_config.reparse_args(args, 'DLMAgent')
    agent, runner = ocs_agent.init_site_agent(args)
    DLM_agent = DLMAgent(agent, args.ip_address, args.port)
    agent.register_process('acq', DLM_agent.acq,
                           DLM_agent._stop_acq, startup=True)
    agent.register_task('set_voltage', DLM_agent.set_voltage)
    agent.register_task('close', DLM_agent._stop_acq)
    agent.register_task('set_over_volt', DLM_agent.set_over_volt)
    runner.run(agent, auto_reconnect=True)
