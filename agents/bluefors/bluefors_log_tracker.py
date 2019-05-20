import random
import time, threading
import numpy as np
import ocs
import glob
import os

import datetime
from datetime import timezone

from autobahn.wamp.exception import ApplicationError
from ocs import ocs_agent, site_config, client_t
from ocs.Lakeshore.Lakeshore372 import LS372

class Bluefors_Agent:
    """Agent to connect to a single Lakeshore 372 device.
        
    Parameters
    ----------
        name: Application Session
        ip:  ip address of agent 
        fake_data: generates random numbers without connecting to LS if True. 

    """
    def __init__(self, agent, log_directory):
        self.lock = threading.Semaphore()
        self.job = None

        self.log_directory = log_directory
        self.file_list = []
        self.date = None # track the day for log rotations, directory format %y-%m-%d
        self.open = False # are file objects opened

        self.log = agent.log
        self.agent = agent

        # Registers bluefors feed
        agg_params = {
            'blocking': {
                         'CH5': {'data': ['CH5 T']},
                         'CH6': {'data': ['CH6 T']},
                        }
        }
        self.agent.register_feed('bluefors',
                                 aggregate=True,
                                 agg_params=agg_params,
                                 buffered=True, buffer_time=1)

    def try_set_job(self, job_name):
        print(self.job, job_name)
        with self.lock:
            if self.job == None:
                self.job = job_name
                return (True, 'ok')
            else:
                return (False, 'Conflict: "%s" is already running.' % self.job)

    def set_job_done(self):
        with self.lock:
            self.job = None

    def init_lakeshore_task(self, session, params=None):
        # TODO: task to refresh log list perhaps?
        ok, msg = self.try_set_job('init')

        self.log.info('Initialized Bluefors log tracking: {status}', status=ok)
        if not ok:
            return ok, msg

        session.set_status('running')

        # since we only work on T logs right now, let's limit to that
        self.file_list = glob.glob("%s/*/CH* T *.log"%self.log_directory)
        print(self.file_list)

        self.set_job_done()
        return True, 'Bluefors log tracking initialized.'

    def start_acq(self, session, params=None):

        ok, msg = self.try_set_job('acq')
        if not ok:
             return ok, msg

        session.set_status('running')
 
        file_objects = {}
        for _file in self.file_list:
            file_objects[_file] = open(_file, 'r')

        # skip over already existing file contents
        for k, v in file_objects.items():
            v.readlines()
 
        print(file_objects) 
        while True:
            with self.lock:
                if self.job == '!acq':
                    break
                elif self.job == 'acq':
                    pass
                else:
                    return 10

            # Handle log rotation
                # check today's date
                    # if stored date is None, store new date and proceed with opening files
                    # else, compare with stored date
                        # has the date changed since last loop iteration?
                            # if no, continue
                            # if yes, close all open file objects, search for new files, store new date
                                    # mark files as closed

            # generate file list
                # temperature/372 logs
                    # glob.glob("%s/%s/CH*.log"%(self.log_directory, self.date))
                # channel logs
                    # glob.glob("%s/%s/Channels*.log"%(self.log_directory, self.date))
                # flowmeter logs
                    # glob.glob("%s/%s/Flowmeter*.log"%(self.log_directory, self.date))
                # Pressure logs
                    # glob.glob("%s/%s/maxigauge*.log"%(self.log_directory, self.date))

            # open file objects
                # if files not open:
                    # open all file objects
                # else:
                    # continue

            for k, v in file_objects.items():
                # this only works on temperature logs right now...
                channel = os.path.basename(k)[:3] #i.e. 'CH6'
                new = v.readline()
                if new != '': 
                    date, _time, data_value = new.strip().split(',')
                    time_str = "%s,%s"%(date, _time)
                    dt = datetime.datetime.strptime(time_str, "%d-%m-%y,%H:%M:%S")
                    timestamp = dt.replace(tzinfo=timezone.utc).timestamp()

                    # Data array to populate
                    data = {
                        'timestamp': timestamp,
                        'block_name': channel,
                        'data': {}
                    }

                    data['data']['%s T'%channel] = data_value
                    #print(k, timestamp, data_value)

                    print("Data: {}".format(data))
                    session.app.publish_to_feed('bluefors', data)

            time.sleep(0.01)

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
    # Get the default ocs argument parser.
    parser = site_config.add_arguments()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--log-directory')

    # Parse comand line.
    args = parser.parse_args()

    # Interpret options in the context of site_config.
    site_config.reparse_args(args, 'BlueforsAgent')
    print('I am following logs located at : %s' % args.log_directory)

    agent, runner = ocs_agent.init_site_agent(args)

    lake_agent = Bluefors_Agent(agent, args.log_directory)

    agent.register_task('init_lakeshore', lake_agent.init_lakeshore_task)
    agent.register_process('acq', lake_agent.start_acq, lake_agent.stop_acq)

    runner.run(agent, auto_reconnect=True)
