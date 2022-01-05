import os
import time
import txaio
import argparse
import numpy as np

import traceback

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import TimeoutLock

class Test_Agent:

    def __init__(self, agent):

        self.agent: ocs_agent.OCSAgent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        self.initialized = False
        self.take_data = False

        agg_params = {'frame_length':60}
        self.agent.register_feed('test_data', record=True, agg_params=agg_params, buffer_time=1)
        pass

    # Task sample
    def sample_task(self, session, params=None):
        try:
            if params == None:
                params = {'feedback_time': [0.181, 0.221, 0.251, 0.281, 0.301]}
                pass

            with open('list-taking.txt', 'a') as f:
                f.write(str(params['feedback_time'])+'\n')
                pass
        except:
            msg = traceback.print_exc()
            self.log.warn(msg)
            pass
        pass

    def start_acq(self, session, params=None):

        with self.lock.acquire_timeout(0, job='upload_cal_curve') as acquired:
            if not acquired:
                self.log.warn("Could not start set_values because "
                              "{} is already running".format(self.lock.job))
                return False, "Could not acquire lock."

            session.set_status('running')

            self.take_data = True

            while self.take_data:
                current_time = time.time()
                data = {
                        'timestamps': [],
                        'block_name': 'test_feed',
                        'data': {}
                        }

                data['timestamps'] = (current_time + np.arange(0,0.1,0.001)).tolist()

                with open('time.log', 'a') as f:
                    f.write(str(current_time)+'\n')
                    pass

                data['data']['noise'] = np.random.rand(100).tolist()

                self.agent.publish_to_feed('test_data', data)
                
                '''
                try:
                    with open('position_copy.log', 'a') as f:
                        with open('/data/wg-data/position.log') as h:
                            position = h.readlines()
                            pass
                        f.write(position[0]+'\n')
                        pass
                except:
                    with open('position_error.txt', 'a') as g:
                        traceback.print_exc(file=g)
                        pass
                    pass
                '''

                time.sleep(1)
                pass

        self.agent.feeds['test_data'].flush_buffer()

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

if __name__=='__main__':
    parser = site_config.add_arguments()
    if parser is None: parser = argparse.ArgumentParser()
    args = parser.parse_args()
    site_config.reparse_args(args, 'Test_Agent')
    agent, runner = ocs_agent.init_site_agent(args)
    test_agent = Test_Agent(agent)
    agent.register_process('acq', test_agent.start_acq, test_agent.stop_acq, startup=True)
    agent.register_task('sample_task',test_agent.sample_task)

    runner.run(agent, auto_reconnect=True)
