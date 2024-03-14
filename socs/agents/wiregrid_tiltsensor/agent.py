
import time

import numpy as np
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock


class WiregridTiltsensorAgent:

    def __init__(self, agent):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.take_data = False

        agg_params = {'frame_length': 60}
        self.agent.register_feed('test_feed',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1.)

    def acq(self, session, params=None):
        """noise to grafana
        **Process** - make 100 random numbers in a single data feed
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

            self.log.info("Starting the count!")

            # Loop
            while self.take_data:
                # About every second, release and acquire the lock
                if time.time() - last_release > 1.:
                    last_release = time.time()
                    if not self.lock.release_and_acquire(timeout=10):
                        print(f"Could not re-acquire lock now held by {self.lock.job}.")
                        return False

                sens_data = {
                    'block_name': 'noise',
                    'timestamps': (last_release + np.arange(0, 0.1, 0.001)).tolist(),
                    'data': {'noise': np.random.rand(100).tolist()}
                }
                """
                with open('time.log', 'a') as f:
                    f.write(str(last_release) + '\n')
                    pass
                """
                # self.log.info(f"sens_data:{sens_data}")
                self.agent.publish_to_feed('test_feed', sens_data)

                # store the session data
                session.data = {'test_data': {
                    'noise': sens_data['data']['noise']
                },
                    'timestamp': last_release}

                time.sleep(1)  # DAQ interval
                # End of loop
            # End of lock acquiring

        self.agent.feeds['test_feed'].flush_buffer()

        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        if self.take_data:
            self.take_data = False
            return True, 'requested to stop takeing data.'
        else:
            return False, 'acq is not currently running.'

    @ocs_agent.param('text', default='hello world', type=str)
    def print(self, session, params):
        """print(text='hello world')
        **Task** - Print some text passed to a Task.
        """
        with self.lock.acquire_timeout(timeout=3.0, job='print') as acquired:
            if not acquired:
                self.log.warn("Lock could not be acquired because it "
                              + f"is held by {self.lock.job}")
                return False

            # Log the text provided to the Agent logs
            self.log.info(f"{params['text']}")

            # Store the text provided in session.data
            session.data = {'text': params['text'],
                            'last_updated': time.time()}

        # bool, 'descriptive text message'
        # True if task succeeds, False if not
        return True, 'Printed text to logs'


def make_parser(parser_in=None):
    if parser_in is None:
        import argparse
        parser_in = argparse.ArgumentParser()

    # pgroup = parser_in.add_argument_group('Agent Options')
    # pgroup.add_argument('--port', dest='port',
    #                    type=int, default=50007,
    #                    help='Port of the beaglebone '
    #                         'running wiregrid encoder DAQ')
    return parser_in


def main(args=None):
    parser_in = make_parser()
    args = site_config.parse_args(agent_class='WiregridTiltsensorAgent',
                                  parser=parser_in,
                                  args=args)
    agent, runner = ocs_agent.init_site_agent(args)

    tiltsensor_agent = WiregridTiltsensorAgent(agent)

    agent.register_process('acq', tiltsensor_agent.acq, tiltsensor_agent.stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
