import os
import random
import argparse
import time
import threading
import numpy as np

from socs.Lakeshore.Lakeshore372 import LS372

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class LS372_Agent:
    """Agent to connect to a single Lakeshore 372 device.

    Args:
        name (ApplicationSession): ApplicationSession for the Agent.
        ip (str): IP Address for the 372 device.
        fake_data (bool, optional): generates random numbers without connecting
            to LS if True.

    """
    def __init__(self, agent, name, ip, fake_data=False):
        self.lock = TimeoutLock()
        self.job = None

        self.name = name
        self.ip = ip
        self.fake_data = fake_data
        self.module = None
        self.thermometers = []

        self.log = agent.log
        self.initialized = False
        self.take_data = False

        self.agent = agent
        # Registers temperature feeds
        agg_params = {
            'frame_length': 10*60 #[sec]
        }
        self.agent.register_feed('temperatures',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def init_lakeshore_task(self, session, params=None):
        """init_lakeshore_task(params=None)

        Perform first time setup of the Lakeshore 372 communication.

        Args:
            params (dict): Parameters dictionary for passing parameters to
                task.

        Parameters:
            auto_acquire (bool, optional): Default is False. Starts data
                acquisition after initialization if True.

        """

        if params is None:
            params = {}

        if self.initialized and not params.get('force', False):
            self.log.info("Lakeshore already initialized. Returning...")
            return True, "Already initialized"

        with self.lock.acquire_timeout(0, job='init') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            if self.fake_data:
                self.res = random.randrange(1, 1000);
                session.add_message("No initialization since faking data")
                self.thermometers = ["thermA", "thermB"]
            else:
                self.module = LS372(self.ip)
                print("Initialized Lakeshore module: {!s}".format(self.module))
                session.add_message("Lakeshore initilized with ID: %s"%self.module.id)

                self.thermometers = [channel.name for channel in self.module.channels]

            self.initialized = True

        # Start data acquisition if requested
        if params.get('auto_acquire', False):
            self.agent.start('acq')

        return True, 'Lakeshore module initialized.'

    def start_acq(self, session, params=None):

        with self.lock.acquire_timeout(0, job='acq') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')
            self.log.info("Starting data acquisition for {}".format(self.agent.agent_address))

            self.take_data = True
            while self.take_data:
                if self.fake_data:

                    data = {
                        'timestamp': time.time(),
                        'block_name': 'fake-data',
                        'data': {}
                    }
                    for therm in self.thermometers:
                        reading = np.random.normal(self.res, 20)
                        data['data'][therm] = reading
                    time.sleep(.1)
                    
                else:
                    active_channel = self.module.get_active_channel()
                    data = {
                        'timestamp': time.time(),
                        'block_name': active_channel.name,
                        'data': {}
                    }

                    # Collect both temperature and resistance values from each Channel
                    data['data'][active_channel.name + ' T'] = self.module.get_temp(unit='kelvin', chan=active_channel.channel_num)
                    data['data'][active_channel.name + ' R'] = self.module.get_temp(unit='ohms', chan=active_channel.channel_num)
                    time.sleep(.01)

                session.app.publish_to_feed('temperatures', data)

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        """
        Stops acq process.
        """
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop taking data.'
        else:
            return False, 'acq is not currently running'

    def set_heater_range(self, session, params):
        """
        Adjust the heater range for servoing cryostat. Wait for a specified
        amount of time after the change.

        :param params: dict with 'range', 'wait' keys
        :type params: dict

        range - the heater range value to change to
        wait - time in seconds after changing the heater value to wait, allows
               the servo to adjust to the new heater range, typical value of
               ~600 seconds
        """
        with self.lock.acquire_timeout(0, job='set_heater_range') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            heater_string = params.get('heater', 'sample')
            if heater_string.lower() == 'sample':
                heater = self.module.sample_heater
            elif heater_string.lower() == 'still':
                heater = self.module.still_heater

            current_range = heater.get_heater_range()

            if params['range'] == current_range:
                print("Current heater range matches commanded value. Proceeding unchanged.")
            else:
                heater.set_heater_range(params['range'])
                time.sleep(params['wait'])

        return True, f'Set {heater_string} heater range to {params["range"]}'

    def set_excitation_mode(self, session, params):
        """
        Set the excitation mode of a specified channel.

        :param params: dict with "channel" and "mode" keys for Channel.set_excitation_mode()
        :type params: dict
        """

        with self.lock.acquire_timeout(0, job='set_excitation_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.channels[params['channel']].set_excitation_mode(params['mode'])
            session.add_message(f'post message in agent for Set channel {params["channel"]} excitation mode to {params["mode"]}')
            print(f'print statement in agent for Set channel {params["channel"]} excitation mode to {params["mode"]}')

        return True, f'return text for Set channel {params["channel"]} excitation mode to {params["mode"]}'

    def set_excitation(self, session, params):
        """
        Set the excitation voltage/current value of a specified channel.

        :param params: dict with "channel" and "value" keys for Channel.set_excitation()
        :type params: dict
        """
        with self.lock.acquire_timeout(0, job='set_excitation') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            current_excitation = self.module.channels[params['channel']].get_excitation()

            if params['value'] == current_excitation:
                print(f'Channel {params["channel"]} excitation already set to {params["value"]}')
            else:
                self.module.channels[params['channel']].set_excitation(params['value'])
                session.add_message(f'Set channel {params["channel"]} excitation to {params["value"]}')
                print(f'Set channel {params["channel"]} excitation to {params["value"]}')

        return True, f'Set channel {params["channel"]} excitation to {params["value"]}'

    def set_pid(self, session, params):
        """
        Set the PID parameters for servo control of fridge.

        :param params: dict with "P", "I", and "D" keys for Heater.set_pid()
        :type params: dict
        """
        with self.lock.acquire_timeout(0, job='set_pid') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.sample_heater.set_pid(params["P"], params["I"], params["D"])
            session.add_message(f'post message text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')
            print(f'print text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}')

        return True, f'return text for Set PID to {params["P"]}, {params["I"]}, {params["D"]}'

    def set_active_channel(self, session, params):
        """
        Set the active channel on the LS372.

        :param params: dict with "channel" number
        :type params: dict
        """
        with self.lock.acquire_timeout(0, job='set_active_channel') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            self.module.set_active_channel(params["channel"])
            session.add_message(f'post message text for set channel to {params["channel"]}')
            print(f'print text for set channel to {params["channel"]}')

        return True, f'return text for set channel to {params["channel"]}'

    def set_autoscan(self, session, params):
        """
        Sets autoscan on the LS372.
        :param params: dict with "autoscan" value
        """
        with self.lock.acquire_timeout(0, job='set_autoscan') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            if params['autoscan']:
                self.module.enable_autoscan()
                self.log.info('enabled autoscan')
            else:
                self.module.disable_autoscan()
                self.log.info('disabled autoscan')

        return True, 'Set autoscan to {}'.format(params['autoscan'])

    def servo_to_temperature(self, session, params):
        """Servo to temperature passed into params.

        :param params: dict with "temperature" Heater.set_setpoint() in unites of K
        :type params: dict
        """
        with self.lock.acquire_timeout(0, job='servo_to_temperature') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            # Check we're in correct control mode for servo.
            if self.module.sample_heater.mode != 'Closed Loop':
                session.add_message(f'Changing control to Closed Loop mode for servo.')
                self.module.sample_heater.set_mode("Closed Loop")

            # Check we aren't autoscanning.
            if self.module.get_autoscan() is True:
                session.add_message(f'Autoscan is enabled, disabling for PID control on dedicated channel.')
                self.module.disable_autoscan()

            # Check we're scanning same channel expected by heater for control.
            if self.module.get_active_channel().channel_num != int(self.module.sample_heater.input):
                session.add_message(f'Changing active channel to expected heater control input')
                self.module.set_active_channel(int(self.module.sample_heater.input))

            # Check we're setup to take correct units.
            if self.module.get_active_channel().units != 'kelvin':
                session.add_message(f'Setting preferred units to Kelvin on heater control input.')
                self.module.get_active_channel().set_units('kelvin')

            # Make sure we aren't servoing too high in temperature.
            if params["temperature"] > 1:
                return False, f'Servo temperature is set above 1K. Aborting.'

            self.module.sample_heater.set_setpoint(params["temperature"])

        return True, f'Setpoint now set to {params["temperature"]} K'

    def check_temperature_stability(self, session, params):
        """Check servo temperature stability is within threshold.

        :param params: dict with "measurements" and "threshold" parameters
        :type params: dict

        measurements - number of measurements to average for stability check
        threshold - amount within which the average needs to be to the setpoint for stability
        """
        with self.lock.acquire_timeout(0, job='check_temp_stability') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            setpoint = float(self.module.sample_heater.get_setpoint())

            if params is None:
                params = {'measurements': 10, 'threshold': 0.5e-3}

            test_temps = []

            for i in range(params['measurements']):
                test_temps.append(self.module.get_temp())
                time.sleep(.1)  # sampling rate is 10 readings/sec, so wait 0.1 s for a new reading

            mean = np.mean(test_temps)
            session.add_message(f'Average of {params["measurements"]} measurements is {mean} K.')
            print(f'Average of {params["measurements"]} measurements is {mean} K.')

            if np.abs(mean - setpoint) < params['threshold']:
                print("passed threshold")
                session.add_message(f'Setpoint Difference: ' + str(mean - setpoint))
                session.add_message(f'Average is within {params["threshold"]} K threshold. Proceeding with calibration.')

                return True, f"Servo temperature is stable within {params['threshold']} K"

            else:
                print("we're in the else")
                #adjust_heater(t,rest)

        return False, f"Temperature not stable within {params['threshold']}."

    def set_output_mode(self, session, params=None):
        """
        Set output mode of the heater.

        :param params: dict with "heater" and "mode" parameters
        :type params: dict

        heater - Specifies which heater to control. Either 'sample' or 'still'
        mode - Specifies mode of heater. Can be "Off", "Monitor Out", "Open Loop",
                    "Zone", "Still", "Closed Loop", or "Warm up"
        """

        with self.lock.acquire_timeout(0, job='set_output_mode') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            session.set_status('running')

            if params['heater'].lower() == 'still':
                self.module.still_heater.set_mode(params['mode'])
            if params['heater'].lower() == 'sample':
                self.module.sample_heater.set_mode(params['mode'])
            self.log.info("Set {} output mode to {}".format(params['heater'], params['mode']))

        return True, "Set {} output mode to {}".format(params['heater'], params['mode'])

    def set_heater_output(self, session, params=None):
        """
        Set display type and output of the heater.

        :param params: dict with "heater", "display", and "output" parameters
        :type params: dict

        heater - Specifies which heater to control. Either 'sample' or 'still'
        output - Specifies heater output value.
                    If display is set to "Current" or heater is "still", can be any number between 0 and 100.
                    If display is set to "Power", can be any number between 0 and the maximum allowed power.

        display (opt)- Specifies heater display type. Can be "Current" or "Power".
                        If None, heater display is not reset before setting output.

        """

        with self.lock.acquire_timeout(0, job='set_heater_output') as acquired:
            if not acquired:
                self.log.warn(f"Could not start init because "
                              f"{self.lock.job} is already running")
                return False, "Could not acquire lock"

            heater = params['heater'].lower()
            output = params['output']

            display = params.get('display', None)

            if heater == 'still':
                self.module.still_heater.set_heater_output(output, display_type=display)
            if heater.lower() == 'sample':
                self.log.info("display: {}\toutput: {}".format(display, output))
                self.module.sample_heater.set_heater_output(output, display_type=display)

            self.log.info("Set {} heater display to {}, output to {}".format(heater, display, output))

            session.set_status('running')

            data = {'timestamp': time.time(),
                    'block_name': '{}_heater_out'.format(heater),
                    'data': {'{}_heater_out'.format(heater): output}
                    }
            session.app.publish_to_feed('temperatures', data)

        return True, "Set {} display to {}, output to {}".format(heater, display, output)

def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address')
    pgroup.add_argument('--serial-number')
    pgroup.add_argument('--mode')
    pgroup.add_argument('--fake-data', type=int, default=0,
                        help='Set non-zero to fake data, without hardware.')
    pgroup.add_argument('--auto-acquire', type=bool, default=True,
                        help='Automatically start data acquisition on startup')

    return parser

if __name__ == '__main__':
    # Get the default ocs argument parser.
    site_parser = site_config.add_arguments()

    parser = make_parser(site_parser)

    # Parse comand line.
    args = parser.parse_args()

    # Automatically acquire data if requested (default)
    init_params = False
    if args.auto_acquire:
        init_params = {'auto_acquire': True}

    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'Lakeshore372Agent')
    print('I am in charge of device with serial number: %s' % args.serial_number)

    agent, runner = ocs_agent.init_site_agent(args)

    lake_agent = LS372_Agent(agent, args.serial_number, args.ip_address , fake_data=args.fake_data)

    agent.register_task('init_lakeshore', lake_agent.init_lakeshore_task,
                        startup=init_params)
    agent.register_task('set_heater_range', lake_agent.set_heater_range)
    agent.register_task('set_excitation_mode', lake_agent.set_excitation_mode)
    agent.register_task('set_excitation', lake_agent.set_excitation)
    agent.register_task('set_pid', lake_agent.set_pid)
    agent.register_task('set_autoscan', lake_agent.set_autoscan)
    agent.register_task('set_active_channel', lake_agent.set_active_channel)
    agent.register_task('servo_to_temperature', lake_agent.servo_to_temperature)
    agent.register_task('check_temperature_stability', lake_agent.check_temperature_stability)
    agent.register_task('set_output_mode', lake_agent.set_output_mode)
    agent.register_task('set_heater_output', lake_agent.set_heater_output)
    agent.register_process('acq', lake_agent.start_acq, lake_agent.stop_acq)

    runner.run(agent, auto_reconnect=True)
