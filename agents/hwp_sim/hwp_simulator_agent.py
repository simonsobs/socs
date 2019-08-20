from ocs import ocs_agent, site_config, client_t
# import random
import time
import threading
import serial
# import os, sys
from ocs.ocs_twisted import TimeoutLock

from autobahn.wamp.exception import ApplicationError

class HWPSimulator:
    def __init__(self, port='/dev/ttyACM0', baud=9600, timeout=0.1):
        self.com = serial.Serial(port=port, baudrate=baud, timeout=timeout)

    def read(self):
        """
        Reads data from an Arduino. First decodes the read data, then splits 
        the read line to remove doubled values and takes the second one.
        """
        try: 
            data = bytes.decode(self.com.readline()[:-2])
            sin_data = float(data.split(' ')[1])
            return sin_data
        except Exception as e:
            print(e)


class HWPSimulatorAgent:

    def __init__(self, agent, port='/dev/ttyACM0'):
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()
        self.port = port
        self.take_data = False
        self.arduino = HWPSimulator(port=self.port)

        self.initialized = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('amplitudes', record=True, agg_params=agg_params,buffer_time=1)


    def init_arduino(self):
        """
        Initializes the Arduino connection.
        """
        if self.initialized:
            return True, "Already initialized."

        with self.lock.acquire_timeout(timeout=0, job='init') as acquired:
            if not acquired:
                self.log.warn("Could not start init because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."
            try:
                self.arduino.read()
            except ValueError:
                pass
            print("Arduino HWP Simulator initialized.")

        self.initialized = True
        return True, 'Arduino HWP Simulator initialized.'


    def start_acq(self, session, params):
        """Starts acquiring data.

        Args:
            sampling_frequency (float):
                Sampling frequency for data collection. Defaults to 2.5 Hz

        """
        f_sample = params.get('sampling_frequency', 2.5)
        sleep_time = 1/f_sample - 0.1

        if not self.initialized:
            self.init_arduino()

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn("Could not start acq because {} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                data = {'timestamp':time.time(), 'block_name':'amps','data':{}}

                data['data']['amplitude'] = self.arduino.read()
                time.sleep(sleep_time)
                self.agent.publish_to_feed('amplitudes',data)

            self.agent.feeds['amplitudes'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops the data acquisiton.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running.'


if __name__ == '__main__':
    parser = site_config.add_arguments()

    pgroup = parser.add_argument_group('Agent Options')
    
    args = parser.parse_args()

    site_config.reparse_args(args, 'HWPSimulatorAgent')

    agent, runner = ocs_agent.init_site_agent(args)
    
    arduino_agent = ArduinoAgent(agent)

    agent.register_task('init_arduino', arduino_agent.init_arduino)
    agent.register_process('acq', arduino_agent.start_acq, arduino_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)
