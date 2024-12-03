import argparse
import datetime
import glob
import os
import re
import threading
import time

import txaio
from ocs import ocs_agent, site_config

# Notes:
# Each Lakeshore log gets its own "block" due to tracking the logs
# being somewhat tricky. If a block structure is established and
# then the thermometer removed from the scan, say if the user
# switches to scanning a single channel, then the block structure
# won't be reconstructed and thus won't match the existing
# structure, causing an error.

# For logging
txaio.use_twisted()
LOG = txaio.make_logger()


class LogTracker:
    """Log Tracking helper class. Always tracks current date's logs.

    Parameters
    ----------
    log_dir : str
        Top level log directory

    Attributes
    ----------
    log_dir : str
        Top level log directory
    date : datetime.date
        Today's date. Used to determine the active log directory
    file_objects : dict
        A dictionary with filenames as keys, and another dict as the value.
        Each of these sub-dictionaries has two keys, "file_object", and
        "stat_results", with the open file object, and os.stat results as
        values, respectively. For example::

            {'CH6 T 21-05-27.log':
                {'file_object': <_io.TextIOWrapper name='CH6 T 21-05-27.log' mode='r' encoding='UTF-8'>,
                'stat_results': os.stat_result(st_mode=33188,
                                               st_ino=1456748,
                                               st_dev=65024,
                                               st_nlink=1,
                                               st_uid=1000,
                                               st_gid=1000,
                                               st_size=11013,
                                               st_atime=1622135813,
                                               st_mtime=1622135813,
                                               st_ctime=1622135813)
                }
            }

    """

    def __init__(self, log_dir):
        self.log_dir = log_dir
        self.date = datetime.date.fromtimestamp(time.time())
        self.file_objects = {}

    def _build_file_list(self):
        """Get list of files to open.

        Assumes all logs are set to log to same top level directory,
        i.e. /home/bluefors/logs/

        """
        date_str = self.date.strftime("%y-%m-%d")
        file_list = glob.glob("{}/{}/*.log".format(self.log_dir,
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
            self.file_objects[filename] = {"file_object": open(filename, 'r'),
                                           "stat_results": os.stat(filename)}
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
            self.open_all_logs()

    def reopen_file(self, filename):
        """If a file is already open and a new inode is detected, reopen the
        file. Returns the last line of the file.

        Parameters
        ----------
        filename : str
            Full path to filename to open

        """
        self.file_objects[filename] = {"file_object": open(filename, 'r'),
                                       "stat_results": os.stat(filename)}
        lines = self.file_objects[filename]["file_object"].readlines()
        return lines[-1]

    def open_all_logs(self):
        """Open today's logs and move to end of files."""
        file_list = self._build_file_list()

        self.file_objects = {}
        for _file in file_list:
            self._open_file(_file)

        for k, v in self.file_objects.items():
            v['file_object'].readlines()

    def close_all_files(self):
        """Close all the files tracked by the LogTracker."""
        for k, v in self.file_objects.items():
            v['file_object'].close()
            print("Closed file: {}".format(k))

        self.file_objects = {}


class LogParser:
    """Log Parsing helper class.

    Knows the internal formats for each log type. Used to loop over all
    logs tracked by a LogTracker and publish their contents to an OCS Feed.

    Parameters
    ----------
    tracker : LogTracker
        log tracker that contains paths and file objects to parse
    mode : str
        Operating mode for the log tracker. Either "follow" or "poll",
        defaulting to "follow". In "follow" mode the Tracker will read the
        next line in the file if able to. In "poll" mode stats about the
        file are used to determine if it was updated since the last read,
        and if it has been the file is reopened to get the last line. This
        is more I/O intensive, but is useful in certain configurations.
    stale_time : int
        Time in minutes which represents how fresh data in the bluefors
        logs must be when we open them in order to publish to OCS. This
        ensures we don't reopen a file much later than when they were
        collected and publish "stale" data to the OCS live HK system.

    """

    def __init__(self, tracker, mode="follow", stale_time=2):
        self.log_tracker = tracker
        self.patterns = {'channels': ['v11', 'v2', 'v1', 'turbo1', 'v12', 'v3', 'v10',
                                      'v14', 'v4', 'v13', 'compressor', 'v15', 'v5',
                                      'hs-still', 'v21', 'v16', 'v6', 'scroll1', 'v17',
                                      'v7', 'scroll2', 'v18', 'v8', 'pulsetube', 'v19',
                                      'v20', 'v9', 'hs-mc', 'ext'],
                         'status': ['tc400errorcode', 'tc400ovtempelec',
                                    'tc400ovtemppump', 'tc400setspdatt',
                                    'tc400pumpaccel', 'tc400commerr',
                                    'tc400errorcode_2', 'tc400ovtempelec_2',
                                    'tc400ovtemppump_2', 'tc400setspdatt_2',
                                    'tc400pumpaccel_2', 'tc400commerr_2',
                                    'nxdsf', 'nxdsct', 'nxdst', 'nxdsbs', 'nxdstrs',
                                    'ctrl_pres', 'cpastate', 'cparun', 'cpawarn',
                                    'cpaerr', 'cpatempwi', 'cpatempwo', 'cpatempo',
                                    'cpatemph', 'cpalp', 'cpalpa', 'cpahp', 'cpahpa',
                                    'cpadp', 'cpacurrent', 'cpahours', 'cpapscale',
                                    'cpascale', 'cpatscale', 'cpasn', 'cpamodel',
                                    'ctrl_pres_ok', 'ctr_pressure_ok'],
                         'heater': ["a1_u", "a1_r_lead", "a1_r_htr", "a2_u",
                                    "a2_r_lead", "a2_r_htr", "htr", "htr_range"]}
        self.mode = mode
        self.stale_time = stale_time

    @staticmethod
    def timestamp_from_str(time_string):
        """Convert time string from Bluefors log file into a UNIX timestamp.

        Parameters
        ----------
        time_string : str
            String in format "%d-%m-%y,%H:%M:%S"

        Returns
        -------
        float
            UNIX timestamp

        """
        dt = datetime.datetime.strptime(time_string, "%d-%m-%y,%H:%M:%S")
        timestamp = dt.timestamp()
        return timestamp

    def _parse_single_value_log(self, new_line, log_name):
        """Parses a simple single value log. Valid for LS372 and flowmeter log
        files.

        Parameters
        ----------
        new_line : str
            The new line read by the Parser
        log_name : str
            The name of the log, returned by self.identify_log()
        """
        date, _time, data_value = new_line.strip().split(',')
        time_str = "%s,%s" % (date, _time)
        timestamp = self.timestamp_from_str(time_str)

        # Data array to populate
        data = {
            'timestamp': timestamp,
            'block_name': log_name,
            'data': {}
        }

        data['data'][log_name] = float(data_value)

        return data

    def _parse_maxigauge_log(self, new_line, log_name):
        """Parse the maxigauge logs.

        Parameters
        ----------
        new_line : str
            The new line read by the Parser
        log_name : str
            The name of the log, returned by self.identify_log()

        """
        ts, *channels = new_line.strip().split('CH')
        time_str = ts.strip(',')
        timestamp = self.timestamp_from_str(time_str)

        ch_data = {}
        for ch in channels:
            ch_num, _, state, value, *_ = ch.split(',')
            ch_data["pressure_ch{}_state".format(ch_num)] = int(state)
            ch_data["pressure_ch{}".format(ch_num)] = float(value)

        data = {
            'timestamp': timestamp,
            'block_name': log_name,
            'data': ch_data
        }

        return data

    def _parse_multi_value_log(self, new_line, log_type, log_name):
        """Parse a log containing multiple values on each line. Valid for
        Channel, Status, and heater logs.

        Patterns to search for are all known by the parser a class attribute.

        Parameters
        ----------
        new_line : str
            The new line read by the Parser
        log_type : str
            Log type as identified by self.identify_log, used to select search
            patterns
        log_name : str
            The name of the log, returned by self.identify_log()

        """
        date, _time, *_ = new_line.strip().split(',')
        time_str = "%s,%s" % (date, _time)
        timestamp = self.timestamp_from_str(time_str)

        data_array = {}
        for pattern in self.patterns[log_type]:
            regex = re.compile(rf'{pattern},([0-9\.\+\-E]+)')
            m = regex.search(new_line)

            # skip patterns that don't exist in this log
            if not m:
                continue

            if log_type == 'channels':
                data_array[pattern.replace('-', '_')] = int(m.group(1))
            else:
                data_array[pattern] = float(m.group(1))

        data = {
            'timestamp': timestamp,
            'block_name': log_name,
            'data': data_array
        }

        return data

    @staticmethod
    def identify_log(filename):
        """Identify type of log return unique identifier

        Parameters
        ----------
        filename : str
            path to file for identification

        Returns
        -------
        tuple
            A tuple containing two strings:
                1. The log type, i.e. 'lakeshore', 'flowmeter'
                2. Unique identifier based on filetype, i.e. 'lakeshore_ch8_p',
                   'pressure_ch1_state'

        """
        # file type: regex search pattern to identify
        file_types = {'lakeshore': '(CH[0-9]+ [T,R,P])',
                      'flowmeter': '(Flowmeter)',
                      'maxiguage': '(maxigauge)',
                      'channels': '(Channels)',
                      'status': '(Status)',
                      'errors': '(Errors)',
                      'heater': '(heaters)'}

        for k, v in file_types.items():
            if re.search(v, filename, flags=re.I):
                _type = k

                m = re.search(file_types[_type], filename, flags=re.I)
                if _type == 'lakeshore':
                    return _type, "{}_{}".format(_type, m.group(0).lower().replace(' ', '_'))
                else:
                    return _type, m.group(0).lower()

        # If nothing matches return None
        return (None, None)

    def read_and_publish_logs(self, app_session):
        """Read a new line from each log file if there is one, and publish its
        contents to the app_session's feed.

        Parameters
        ----------
        app_session : ocs.ocs_agent.OpSession
            session from the ocs_agent, used to publish to bluefors feed

        """
        for k, v in self.log_tracker.file_objects.items():
            log_type, log_name = self.identify_log(k)

            if os.stat(k).st_ino != v['stat_results'].st_ino and self.mode == "poll":
                LOG.debug("New inode found, reopening...")
                new = self.log_tracker.reopen_file(k)
                LOG.debug("File: {f}, Line: {l}", f=k, l=new)
            # In a situation with a samba share mounted via sshfs, reading the
            # nextline didn't reliably work, nor does watching the inode. We'll
            # also check modification times, which maybe we should just do
            # instead of the inode check...
            elif os.stat(k).st_mtime > v['stat_results'].st_mtime and self.mode == "poll":
                LOG.debug("Modification detected, reopening...")
                new = self.log_tracker.reopen_file(k)
                LOG.debug("File: {f}, Line: {l}", f=k, l=new)
            else:
                new = v['file_object'].readline()
            if new == '':
                continue

            if log_type in ['lakeshore', 'flowmeter']:
                data = self._parse_single_value_log(new, log_name)
            elif log_type == 'maxiguage':
                data = self._parse_maxigauge_log(new, log_name)
            elif log_type in ['channels', 'status', 'heater']:
                data = self._parse_multi_value_log(new, log_type, log_name)
            elif log_type == 'errors':
                LOG.info("The Bluefors Agent cannot process error logs. "
                         + "Not publishing.")
                data = None
            else:
                LOG.warn("Warning: Unknown log type. Skipping publish step. "
                         + "This probably shouldn't happen.")
                LOG.warn("Filename: {}".format(k))
                data = None
            LOG.debug("Data: {d}", d=data)

            # Don't publish if we didn't load anything
            if data is None:
                continue
            if data['data'] == {}:
                continue

            # If the file was reopened due to an inode change we don't know
            # if the last line is recent enough to be worth publishing. Check
            if (time.time() - data['timestamp']) < int(self.stale_time) * 60:
                app_session.app.publish_to_feed('bluefors', data)
            else:
                LOG.warn("Not publishing stale data. Make sure your log "
                         + "file sync is done at a rate faster than once ever "
                         + "{x} minutes.", x=self.stale_time)


class BlueforsAgent:
    """Agent to track the Bluefors logs generated by an LD400.

    Parameters
    ----------
    log_directory : str
        Top level log directory for the Bluefors logs

    """

    def __init__(self, agent, log_directory):
        self.lock = threading.Semaphore()
        self.job = None

        self.log_tracker = LogTracker(log_directory)

        self.log = agent.log
        self.agent = agent

        # Registers bluefors feed
        agg_params = {
            'frame_length': float(os.environ.get("FRAME_LENGTH", 10 * 60))  # [sec]
        }
        self.log.debug("frame_length set to {length}",
                       length=agg_params['frame_length'])
        self.agent.register_feed('bluefors',
                                 record=True,
                                 agg_params=agg_params,
                                 )

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

    def acq(self, session, params=None):
        """acq()

        **Process** - Monitor and publish data from the Bluefors log files.

        """

        ok, msg = self.try_set_job('acq')
        if not ok:
            return ok, msg

        # Create file objects for all logs in today's directory
        self.log_tracker.open_all_logs()

        # Determine parser configuration
        stale_time = os.environ.get("STALE_TIME", 2)
        mode = os.environ.get("MODE", "follow")

        # Setup the Parser object with tracking info
        parser = LogParser(self.log_tracker, mode, stale_time)

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

            # Check for new lines and publish to feed
            parser.read_and_publish_logs(session)

            time.sleep(0.01)

        self.set_job_done()
        return True, 'Acquisition exited cleanly.'

    def _stop_acq(self, session, params=None):
        ok = False
        with self.lock:
            if self.job == 'acq':
                self.job = '!acq'
                ok = True
        return (ok, {True: 'Requested process stop.',
                     False: 'Failed to request process stop.'}[ok])


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--log-directory')

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    # Setup argument parser
    parser = make_parser()
    args = site_config.parse_args(agent_class='BlueforsAgent',
                                  parser=parser,
                                  args=args)
    LOG.info('I am following logs located at : %s' % args.log_directory)

    agent, runner = ocs_agent.init_site_agent(args)

    bluefors_agent = BlueforsAgent(agent, args.log_directory)

    agent.register_process('acq', bluefors_agent.acq,
                           bluefors_agent._stop_acq, startup=True)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
