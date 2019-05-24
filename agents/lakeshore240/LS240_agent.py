from ocs import ocs_agent, site_config, client_t
from socs.Lakeshore.Lakeshore240 import Module
import random
import time
import threading
import os

from autobahn.wamp.exception import ApplicationError

class LS240_Agent:

    def __init__(self, agent,
                 num_channels=2,
                 fake_data=False,
                 port="/dev/ttyUSB0"):
        print(num_channels)
        self.active = True
        self.agent = agent
        self.log = agent.log
        self.lock = threading.Semaphore()
        self.job = None
        self.fake_data = fake_data
        self.module = None
        self.port = port
        self.thermometers = ['Channel {}'.format(i + 1) for i in range(num_channels)]
        self.log = agent.log

        # Registers Temperature and Voltage feeds
        agg_params = {
            'frame_length': 60,
        }
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)


    # Exclusive access management.
    def try_set_job(self, job_name):
        with self.lock:
            if self.job == None:
                self.job = job_name
                return True, 'ok.'
            return False, 'Conflict: "%s" is already running.' % self.job

    def set_job_done(self):
        with self.lock:
            self.job = None

    # Task functions.
    def init_lakeshore_task(self, session, params=None):
        """
        Task to initialize Lakeshore 240 Module.
        """
        ok, msg = self.try_set_job('init')

        self.log.info('Initialized Lakeshore: {status}', status=ok)
        if not ok:
            return ok, msg

        session.set_status('starting')

        if self.fake_data:
            session.add_message("No initialization since faking data")
            # self.thermometers = ["chan_1", "chan_2"]

        else:
            try:
                self.module = Module(port=self.port)
                print("Initialized Lakeshore module: {!s}".format(self.module))
                session.add_message("Lakeshore initialized with ID: %s"%self.module.inst_sn)

                # self.thermometers = ["chan_1", "chan_2"]

            except Exception as e:
                print(e)

        self.set_job_done()
        return True, 'Lakeshore module initialized.'

    def set_values(self, session, params=None):
        """
        A task to set sensor parameters for a Lakeshore240 Channel

        Args:

            channel (int): Channel number to  set

        Optional Args:
            sensor (int, 1, 2, or 3):
                1 = Diode, 2 = PlatRTC, 3 = NTC RTD
            auto_range (int, 0 or 1):
                Must be 0 or 1. Specifies if channel should use autorange.
            range (int 0-8):
                Specifies range if autorange is false. Only settable for NTC RTD.
                    0 = 10 Ohms (1 mA)
                    1 = 30 Ohms (300 uA)
                    2 = 100 Ohms (100 uA)
                    3 = 300 Ohms (30 uA)
                    4 = 1 kOhm (10 uA)
                    5 = 3 kOhms (3 uA)
                    6 = 10 kOhms (1 uA)
                    7 = 30 kOhms (300 nA)
                    8 = 100 kOhms (100 nA)
            current_reversal (int, 0 or 1):
                Specifies if input current reversal is on or off.
                Always 0 if input is a diode.
            units (int, 1-4):
                Specifies preferred units parameter, and sets the units
                for alarm settings.
                    1 = Kelvin
                    2 = Celsius
                    3 = Sensor
                    4 = Fahrenheit
            enabled (int, 0 or 1):
                sets if channel is enabled
            name (str):
                sets name of channel
        """
        ok, msg = self.try_set_job('set_values')

        self.log.info('set_values: {status}', status=ok)
        if not ok:
            return ok, msg

        if params is None:
            params = {}

        self.module.channels[params['channels']].set_values(
            sensor=params.get('sensor'),
            auto_range=params.get('auto_range'),
            range=params.get('range'),
            current_reversal=params.get('current_reversal'),
            unit=params.get('unit'),
            enabled=params.get('enabled'),
            name=params.get('name'),
        )

        self.set_job_done()
        return True, 'Set values for channel {}'.format(params['channel'])


    # Process functions.
    def start_acq(self, session, params=None):
        """Start data acquisition.

        Args:
            params (dict): params dictionary with keys:
                'sampling_frequency' (float): sampling frequency for data collection
                                              defaults to 2.5 Hz

        """
        if params is None:
            params = {}

        f_sample = params.get('sampling_frequency', 2.5)

        sleep_time = 1/f_sample - 0.01
        ok, msg = self.try_set_job('acq')
        if not ok: return ok, msg
        session.set_status('running')

        while True:
            with self.lock:
                if self.job == '!acq':
                    break
                elif self.job == 'acq':
                    pass
                else:
                    return 10

            data = {
                'timestamp': time.time(),
                'block_name': 'temps',
                'data': {}
            }

            if self.fake_data:
                for therm in self.thermometers:
                    data['data'][therm + ' T'] = random.randrange(250, 350)
                    data['data'][therm + ' V'] = random.randrange(250, 350)
                time.sleep(.2)

            else:
                for i, therm in enumerate(self.thermometers):
                    data['data'][therm + ' T'] = self.module.channels[i].get_reading(unit='K')
                    data['data'][therm + ' V'] = self.module.channels[i].get_reading(unit='S')

                time.sleep(sleep_time)

            session.app.publish_to_feed('temperatures', data)

        self.agent.feeds['temperatures'].flush_buffer()
        self.set_job_done()
        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        ok = False
        with self.lock:
            if self.job =='acq':
                self.job = '!acq'
                ok = True
        return (ok, {True: 'Requested process stop.',
                     False: 'Failed to request process stop.'}[ok])


if __name__ == '__main__':
    parser = site_config.add_arguments()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--num-channels', default='2')
    pgroup.add_argument('--mode')
    pgroup.add_argument('--fake-data', default='0')

    # Parse comand line.
    args = parser.parse_args()

    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Lakeshore240Agent')

    num_channels = int(args.num_channels)
    fake_data = int(args.fake_data)

    # Finds usb-port for device
    # This should work for devices with the cp210x driver
    device_port = ""

    # This exists if udev rules are setup properly for the 240s
    if os.path.exists('/dev/{}'.format(args.serial_number)):
        device_port = "/dev/{}".format(args.serial_number)

    elif os.path.exists('/dev/serial/by-id'):
        ports = os.listdir('/dev/serial/by-id')
        for port in ports:
            if args.serial_number in port:
                device_port = "/dev/serial/by-id/{}".format(port)
                print("Found port {}".format(device_port))
                break

    if device_port or fake_data:
        agent, runner = ocs_agent.init_site_agent(args)

        therm = LS240_Agent(agent, num_channels=num_channels,
                            fake_data=fake_data, port=device_port)

        agent.register_task('init_lakeshore', therm.init_lakeshore_task)
        agent.register_process('acq', therm.start_acq, therm.stop_acq)

        runner.run(agent, auto_reconnect=True)

    else:
        print("Could not find device with sn {}".format(args.serial_number))
