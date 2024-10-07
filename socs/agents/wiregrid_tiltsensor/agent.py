import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import Pacemaker, TimeoutLock

from socs.agents.wiregrid_tiltsensor.drivers import connect


class WiregridTiltSensorAgent:
    """ Agent to record the wiregrid tilt sensor data.
    The tilt sensor data is sent via serial-to-ethernet converter.

    Args:
        ip (str): IP address of the serial-to-ethernet converter
        port (int or str): Asigned port for the tilt sensor
            The converter has four D-sub ports to control
            multiple devices is determined
            by the ethernet port number of converter.
        sensor_type (str): Type of tilt sensor
            There are twp types of tilt sensor,
            and this argument is used for specifying
            to communicate with whichtilt sensor.
            This argument should be 'DWL' or 'sherborne'.
    """

    def __init__(self, agent, ip, port, sensor_type=None):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False

        self.ip = ip
        self.port = int(port)
        self.sensor_type = sensor_type
        self.tiltsensor = connect(self.ip, self.port, self.sensor_type)
        self.pm = Pacemaker(2, quantize=True)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('wgtiltsensor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    def acq(self, session, params=None):
        """acq()

        **Process** - Run data acquisition.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {'tiltsensor_data': {
                    'angleX': the angle in X-axis of tilt sensor,
                    'angleY': the angle in Y-axis of tilt sensor,
                    'temperatureX': the temperature in X-axis of tilt sensor
                                    this is available for only sherborne,
                    'temperatureY': the temperature in Y-axis of tilt sensor
                                    this is available for only sherborne
                    },
                'timestamp': timestamp when it updates tilt sensor data
                }
        """

        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not start acq because {} is already running'
                )

            # Initialize a take_data flag
            self.take_data = True
            last_release = time.time()

            tiltsensor_data = {
                'timestamp': 0,
                'block_name': 'wgtiltsensor',
                'data': {
                    'angleX': -999,
                    'angleY': -999,
                    'temperatureX': -999,
                    'temperatureY': -999,
                },
            }

            self.log.info("Starting the count!")

            # Loop
            while self.take_data:
                # About every second, release and acquire the lock
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        print(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False

                # data taking
                current_time = time.time()
                msg, angles = self.tiltsensor.get_angle()
                if self.sensor_type == 'sherborne':
                    msg, temperatures = self.tiltsensor.get_temp()

                tiltsensor_data['timestamp'] = current_time
                tiltsensor_data['data']['angleX'] = angles[0]
                tiltsensor_data['data']['angleY'] = angles[1]
                if self.sensor_type == 'sherborne':
                    tiltsensor_data['data']['temperatureX'] = temperatures[0]
                    tiltsensor_data['data']['temperatureY'] = temperatures[1]

                self.agent.publish_to_feed('wgtiltsensor', tiltsensor_data)

                # store the session data
                session.data = {
                    'tiltsensor_data': {
                        'angleX': tiltsensor_data['data']['angleX'],
                        'angleY': tiltsensor_data['data']['angleY'],
                        'temperatureX': tiltsensor_data['data']['temperatureX'],
                        'temperatureY': tiltsensor_data['data']['temperatureY']
                    },
                    'timestamp': current_time
                }

                self.pm.sleep()  # DAQ interval
                # End of loop
            # End of lock acquiring

        self.agent.feeds['wgtiltsensor'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop takeing data.'
        else:
            return False, 'acq is not currently running.'

    def reset(self, session, params=None):
        """reset()

        **Task** - Reset the tiltsensor if the type of tiltsensor is sherborne.

        Notes:
            The most recent data collected is stored in session.data in the
            structure::

                >>> response.session['data']
                {'reset': bool whether the reset successful or not
                 'timestamp': timestamp when this command is performed
                }
        """

        with self.lock.acquire_timeout(timeout=3.0, job='reset') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False

            if self.sensor_type != 'sherborne':
                return False, "This type of tiltsensor cannot reset."
            else:
                # Log the text provided to the Agent logs
                self.log.info("running reset")
                # Execute reset()
                self.tiltsensor.reset()
                # Store the timestamp when reset is performed in session.data
                session.data = {'reset': True,
                                'timestamp': time.time()}

        # True if task succeeds, False if not
        return True, 'Reset the tiltsensor'


def make_parser(parser_in=None):
    if parser_in is None:
        import argparse
        parser_in = argparse.ArgumentParser()

    pgroup = parser_in.add_argument_group('Agent Options')
    pgroup.add_argument('--ip-address', dest='ip', type=str, default=None,
                        help='The ip adress of the serial-to-ethernet converter')
    pgroup.add_argument('--port', dest='port', type=str, default=None,
                        help='The assigned port of the serial-to-ethernet converter '
                             'for the tilt sensor')
    pgroup.add_argument('--sensor-type',
                        dest='sensor_type',
                        type=str, default=None,
                        help='The type of tilt sensor '
                             'running wiregrid tilt sensor DAQ')
    return parser_in


def main(args=None):
    parser_in = make_parser()
    args = site_config.parse_args(agent_class='WiregridTiltSensorAgent',
                                  parser=parser_in,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    tiltsensor_agent = WiregridTiltSensorAgent(agent,
                                               ip=args.ip,
                                               port=args.port,
                                               sensor_type=args.sensor_type)

    agent.register_process('acq',
                           tiltsensor_agent.acq,
                           tiltsensor_agent.stop_acq,
                           startup=True)
    agent.register_task('reset', tiltsensor_agent.reset)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
