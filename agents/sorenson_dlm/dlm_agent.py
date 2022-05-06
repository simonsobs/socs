# Script to log and control the Sorenson DLM power supply, for heaters
# Tanay Bhandarkar, Jack Orlowski-Scherer
import time
import socket
import numpy as np
from contextlib import contextmanager
from ocs import site_config, ocs_agent
from ocs.ocs_twisted import TimeoutLock


class DLM:
    def __init__(self, ip_address='10.10.10.21', port=9221, timeout=10):
        self.ip_address = ip_address
        self.port = port
        self.comm = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.comm.connect((self.ip_address, self.port))
        self.comm.settimeout(timeout)
        self.volt_prot = None

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
    '''
    TO DO:
    set_current_and_voltage (simulatneously set current and voltage,
    not sure if needed)

    '''

    def __init__(self, agent, ip_address , port, f_sample=2.5):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.f_sample = f_sample
        self.take_data = False
        self.over_volt = 0
        self.dlm = DLM(ip_address, int(port))
        agg_params = {'frame length': 60, }
        self.agent.register_feed('voltages',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def start_acq(self, session, params=None):
        '''
        Get voltage and current values from the sorenson, publishes them to
        the feed

        Args:
            sampling_frequency: defaults to 2.5Hz
        '''
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency')
        if f_sample is None:
            f_sample = self.f_sample

        sleep_time = 1./f_sample - 0.01
        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                data = {
                    'timestamp': time.time(),
                    'block_name': 'voltages',
                    'data': {}
                }
                voltage_reading = self.dlm.read_voltage()
                current_reading = self.dlm.read_current()
                print('Voltage: {}'.format(voltage_reading))
                print('Current: {}'.format(current_reading))
                data['data']["voltage"] = np.float(voltage_reading)
                data['data']["current"] = np.float(current_reading)

                self.agent.publish_to_feed('voltages', data)
                time.sleep(sleep_time)

            self.agent.feeds['voltages'].flush_buffer()
        return True, 'Acquistion exited cleanly'

    def set_voltage(self, session, params=None):
        """
        Sets voltage of power supply:
        Args:
            voltage (int): Voltage to set.
        """

        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
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
        """
        Sets over voltage protection of power supply:
        Args:
            over_volt (int): Over voltage protection to set
        """

        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            if acquired:
                print("ACQUIRED", params)
                self.dlm.set_overv_prot(params['over_volt'])
                self.over_volt = float(params['over_volt'])
            else:
                return False, 'Could not acquire lock'
        return True, 'Set over voltage protection to {}'.format(params['over_volt'])

    def set_current(self, session, params=None):
        """
        Sets current of power supply:
        Args:
            current (int): Current to set.
        """

        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
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

    def stop_acq(self, session, params=None):
        '''
        End voltage data acquisition
        '''
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'


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
    agent.register_process('acq', DLM_agent.start_acq,
                           DLM_agent.stop_acq, startup=True)
    agent.register_task('set_voltage', DLM_agent.set_voltage)
    agent.register_task('close', DLM_agent.stop_acq)
    agent.register_task('set_over_volt', DLM_agent.set_over_volt)
    runner.run(agent, auto_reconnect=True)
