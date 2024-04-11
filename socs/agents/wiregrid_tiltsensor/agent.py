import time

from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

# DWL drivers
from socs.agents.wiregrid_tiltsensor.drivers.dwl import DWL
# sherborne drivers
from socs.agents.wiregrid_tiltsensor.drivers.sherborne import Sherborne


def connect(tiltsensor_ip, tiltsensor_port, type_tiltsensor):
    if type_tiltsensor == 'DWL':
        tiltsensor = DWL(tcp_ip=tiltsensor_ip, tcp_port=tiltsensor_port, timeout=0.5, isSingle=False, verbose=0)
    elif type_tiltsensor == 'sherborne':
        tiltsensor = Sherborne(tcp_ip=tiltsensor_ip, tcp_port=tiltsensor_port, reset_boot=False, timeout=0.5, verbose=0)
    else:
        raise ('Invalid tiltsensor type')
    return tiltsensor


class WiregridTiltsensorAgent:
    """ Agent to record the wiregrid tilt sensor data.
    """

    def __init__(self, agent, tiltsensor_ip, tiltsensor_port, type_tiltsensor=None):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False

        self.tiltsensor_ip = tiltsensor_ip
        self.tiltsensor_port = tiltsensor_port
        self.type_tiltsensor = type_tiltsensor
        self.tiltsensor = connect(self.tiltsensor_ip, self.tiltsensor_port, self.type_tiltsensor)

        agg_params = {'frame_length': 60}
        self.agent.register_feed('wgtiltsensor',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    def acq(self, session, params=None):
        """acq()
        **Process** - Run data acquisition.
        """
        with self.lock.acquire_timeout(timeout=0, job='acq') as acquired:
            if not acquired:
                self.log.warn(
                    'Could not start acq because {} is already running'
                    .format(self.lock.job))
                return False, 'Could not acquire lock.'

            session.set_status('running')

            # Initialize a take_data flag
            self.take_data = True
            last_release = time.time()

            tiltsensor_data = {'timestamp': 0,
                               'block_name': 'wgtiltsensor',
                               'data': {
                                   'angleX': -999,
                                   'angleY': -999,
                                   'temperatureX': -999,
                                   'temperatureY': -999
                               }
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
                read_status, msg, angles = self.tiltsensor.get_angle()
                if self.type_tiltsensor == 'sherborne':
                    msg, temperatures = self.tiltsensor.get_temp()
                else:
                    pass

                # if read_status:
                tiltsensor_data['timestamp'] = current_time
                tiltsensor_data['data']['angleX'] = angles[0]
                tiltsensor_data['data']['angleY'] = angles[1]
                if self.type_tiltsensor == 'sherborne':
                    tiltsensor_data['data']['temperatureX'] = temperatures[0]
                    tiltsensor_data['data']['temperatureY'] = temperatures[1]
                else:
                    pass

                """
                with open('time.log', 'a') as f:
                    f.write(str(last_release) + '\n')
                    pass
                """
                # self.log.info(f"sens_data:{sens_data}")
                self.agent.publish_to_feed('wgtiltsensor', tiltsensor_data)

                # store the session data
                session.data = {
                    'test_data': {
                        'angleX': tiltsensor_data['data']['angleX'],
                        'angleY': tiltsensor_data['data']['angleY'],
                        'temperatureX': tiltsensor_data['data']['temperatureX'],
                        'temperatureY': tiltsensor_data['data']['temperatureY']
                    },
                    'timestamp': current_time
                }

                time.sleep(0.5)  # DAQ interval
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
        """
        with self.lock.acquire_timeout(timeout=3.0, job='reset') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False

            if self.type_tiltsensor != 'sherborne':
                raise ("This type of tiltsensor cannot reset.")
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
    pgroup.add_argument('--tiltsensor_ip')
    pgroup.add_argument('--tiltsensor_port')
    pgroup.add_argument('--type_tiltsensor',
                        dest='type_tiltsensor',
                        type=str, default=None,
                        help='The type of tilt sensor '
                             'running wiregrid tilt sensor DAQ')
    return parser_in


def main(args=None):
    parser_in = make_parser()
    args = site_config.parse_args(agent_class='WiregridTiltsensorAgent',
                                  parser=parser_in,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    tiltsensor_agent = WiregridTiltsensorAgent(agent,
                                               tiltsensor_ip=args.type_tiltsensor,
                                               tiltsensor_port=args.type_tiltsensor,
                                               type_tiltsensor=args.type_tiltsensor)

    agent.register_process('acq',
                           tiltsensor_agent.acq,
                           tiltsensor_agent.stop_acq,
                           startup=True)
    agent.register_task('reset', tiltsensor_agent.reset)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
