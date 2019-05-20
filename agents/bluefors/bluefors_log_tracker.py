import time
import threading
import glob
import os

import datetime
from datetime import timezone

from ocs import ocs_agent, site_config


class LogTracker:
    def __init__(self, log_dir):
        """Log Tracking helper class. Always tracks current date's logs.

        Parameters
        ----------
        log_dir : str
            Top level log directory

        """
        self.log_dir = log_dir
        self.date = datetime.date.fromtimestamp(time.time())
        self.file_objects = {}

    def _build_file_list(self):
        """Get list of files to open."""
        # generate file list
            # temperature/372 logs
                # glob.glob("%s/%s/CH*.log"%(self.log_directory, self.date))
            # channel logs
                # glob.glob("%s/%s/Channels*.log"%(self.log_directory, self.date))
            # flowmeter logs
                # glob.glob("%s/%s/Flowmeter*.log"%(self.log_directory, self.date))
            # Pressure logs
                # glob.glob("%s/%s/maxigauge*.log"%(self.log_directory, self.date))

        # Only T data right now...
        date_str = self.date.strftime("%y-%m-%d")
        file_list = glob.glob("{}/{}/CH* T *.log".format(self.log_dir,
                                                         date_str))
        return file_list

    def _open_file(self, filename):
        """Open a single file, adding it to self.file_objects.

        Parameters
        ----------
        filename : str
            Full path to filename to open

        """
        if filename not in self.file_objects.keys():
            print("{} not yet open, opening...".format(filename))
            self.file_objects[filename] = open(filename, 'r')
        else:
            pass

    def check_open_files(self):
        """Check all log files are opened.

        The Status logs don't always exist, but we want to catch them when they
        do get generated. This rebuilds the file list and checks all the files in it
        are in the open file objects dictionary.
        """
        file_list = self._build_file_list()
        for f in file_list:
            self._open_file(f)

    def set_active_date(self):
        """Set the active date to today."""
        new_date = datetime.date.fromtimestamp(time.time())

        if new_date > self.date:
            self.close_all_files()
            self.date = new_date
            self.open_file_list()

    def open_all_logs(self):
        """Open today's logs and move to end of files."""
        file_list = self._build_file_list()

        self.file_objects = {}
        for _file in file_list:
            self._open_file(_file)

        for k, v in self.file_objects.items():
            v.readlines()

    def close_all_files(self):
        """Close all the files tracked by the LogTracker."""
        for k, v in self.file_objects.items():
            v.close()
            self.file_objects.pop(k)


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

        self.log_tracker = LogTracker(log_directory)

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
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    def try_set_job(self, job_name):
        print(self.job, job_name)
        with self.lock:
            if self.job is None:
                self.job = job_name
                return (True, 'ok')
            else:
                return (False, 'Conflict: "%s" is already running.' % self.job)

    def set_job_done(self):
        with self.lock:
            self.job = None

    def init_bluefors_task(self, session, params=None):
        ok, msg = self.try_set_job('init')

        self.log.info('Initialized Bluefors log tracking: {status}', status=ok)
        if not ok:
            return ok, msg

        session.set_status('running')

        # since we only work on T logs right now, let's limit to that
        self.file_list = glob.glob("%s/*/CH* T *.log" % self.log_directory)
        print(self.file_list)

        self.set_job_done()
        return True, 'Bluefors log tracking initialized.'

    def start_acq(self, session, params=None):

        ok, msg = self.try_set_job('acq')
        if not ok:
            return ok, msg

        session.set_status('running')

        # Create file objects for all logs in today's directory
        self.log_tracker.open_all_logs()

        while True:
            with self.lock:
                if self.job == '!acq':
                    break
                elif self.job == 'acq':
                    pass
                else:
                    return 10

            # Make sure we're looking at today's logs
            self.log_tracker.set_active_date()

            # Ensure all the logs we want are open
            self.log_tracker.check_open_files()

            for k, v in self.log_tracker.file_objects.items():
                # this only works on temperature logs right now...
                channel = os.path.basename(k)[:3]  # i.e. 'CH6'
                new = v.readline()
                if new != '':
                    date, _time, data_value = new.strip().split(',')
                    time_str = "%s,%s" % (date, _time)
                    dt = datetime.datetime.strptime(time_str, "%d-%m-%y,%H:%M:%S")
                    timestamp = dt.replace(tzinfo=timezone.utc).timestamp()

                    # Data array to populate
                    data = {
                        'timestamp': timestamp,
                        'block_name': channel,
                        'data': {}
                    }

                    data['data']['%s T' % channel] = data_value
                    # print(k, timestamp, data_value)

                    print("Data: {}".format(data))
                    session.app.publish_to_feed('bluefors', data)

            time.sleep(0.01)

        self.set_job_done()
        return True, 'Acquisition exited cleanly.'

    def stop_acq(self, session, params=None):
        ok = False
        with self.lock:
            if self.job == 'acq':
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

    agent.register_task('init_lakeshore', lake_agent.init_bluefors_task)
    agent.register_process('acq', lake_agent.start_acq, lake_agent.stop_acq)

    runner.run(agent, auto_reconnect=True)
