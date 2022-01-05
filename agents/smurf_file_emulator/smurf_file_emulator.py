import time
import os
import argparse
import txaio

from ocs import ocs_agent, site_config


class SmurfFileEmulator:
    """
    OCS Agent for emulating file creation for the smurf system.
    """
    def __init__(self, agent, args):
        self.log = agent.log
        self.file_duration = args.file_duration
        self.stream_id = args.stream_id
        self.basedir = args.base_dir
        if not os.path.exists(self.basedir):
            raise ValueError(f"Basedir {self.basedir} does not exist")

        self.smurfdir = os.path.join(self.basedir, 'smurf')
        self.timestreamdir = os.path.join(self.basedir, 'timestreams')

        self.streaming = False

    def _write_g3_file(self, session_id=None, seq=0, start=None, stop=None):
        """
        Writes fake G3 timestream file.
        """
        if session_id is None:
            session_id = int(time.time())
        if start is None:
            start = time.time()
        if stop is None:
            stop = time.time()

        timecode = f"{session_id}"[:5]
        subdir = os.path.join(self.timestreamdir, timecode, self.stream_id)
        os.makedirs(subdir, exist_ok=True)
        filepath = os.path.join(subdir, f"{session_id}_{seq:0>3}.g3")
        self.log.info(f"Writing file {filepath}")
        with open(filepath, 'w') as f:
            f.write(f'start: {start}\n')
            f.write(f"stop: {stop}\n")
        return filepath



    def _write_smurf_file(self, name, action, action_time=None,
                          prepend_ctime=True, is_plot=False):
        """
        Creates a fake pysmurf ancilliary file containing just the creation
        time of the file.

        For example::

            self._write_smurf_file('IV.npy', 'take_IV')

        will create the file::

            data/smurf/16371/<stream_id>/1637182065_take_IV/1637182065_IV.npy

        Args:
            name (str):
                Name of the file to be created. This should not include the
                ctime since the ctime will be prepended. I.e. "IV.npy" will
                become "<ctime>_IV.npy"
            action (str):
                Pysmurf action name for determining the subdirectory this
                should be written to.
            action_time (float):
                Action timestamp for the file. If None, will set to the current
                time.
        """
        t = int(time.time())
        if action_time is None:
            action_time = t
        action_time = int(action_time)
        timecode = f"{action_time}"[:5]
        dir_type = 'plots' if is_plot else 'outputs'
        subdir = os.path.join(
            self.smurfdir, timecode, self.stream_id, f'{action_time}_{action}',
            dir_type
        )
        os.makedirs(subdir, exist_ok=True)
        if prepend_ctime:
            filepath = os.path.join(subdir, f'{t}_{name}')
        else:
            filepath = os.path.join(subdir, name)
        self.log.info(f"Writing smurf file: {filepath}")
        with open(filepath, 'w') as f:
            f.write(f'start: {time.time()}\n')
        return filepath

    def tune_dets(self, session, params=None):
        """tune_dets()

        **Task** - Emulates files that might come from a general tune dets
        function. These are some of the files found on simons1 registered when
        running the following ops with a single band:

             1. Find-freq
             2. setup_notches
             3. tracking_setup
             4. short g3 stream
        """
        # Find Freq
        action_time = time.time()
        files = ['amp_sweep_freq.txt', 'amp_sweep_resonance.txt',
                 'amp_sweep_resp.txt']
        for f in files:
            self._write_smurf_file(f, 'find_freq',
                                   action_time=action_time)

        # Setup Notches
        action_time = time.time()
        files = ['channel_assignment_b0.txt', 'tune.npy']
        for f in files:
            self._write_smurf_file(f, 'setup_notches',
                                   action_time=action_time)

        # tracking setup
        action_time = time.time()
        fname = f"{int(time.time())}.dat"
        self._write_smurf_file(fname, 'tracking_setup', prepend_ctime=False)

        # Short g3 stream
        self._write_g3_file()

        return True, "Wrote tune files"

    def take_iv(self, session, params=None):
        """take_iv()

        **Task** - Creates files generated associated with iv taking / analysis
        """
        action_time = time.time()
        files = ['iv_analyze.npy', 'iv_bias_all.npy', 'iv_info.npy']
        for f in files:
            self._write_smurf_file(f, 'take_iv',
                                   action_time=action_time)
        return True, "Wrote IV files"

    def take_bias_steps(self, session, params=None):
        """take_bias_steps()

        **Task** - Creates files associated with taking bias steps
        """
        action_time = time.time()
        files = ['bias_step_analysis.npy']
        for f in files:
            self._write_smurf_file(f, 'take_bias_steps',
                                   action_time=action_time)

        return True, "Wrote Bias Step Files"

    def bias_dets(self, session, params=None):
        """bias_dets()

        **Task** - Creates files associated with biasing dets, which is none.
        """
        return True, 'Wrote det biasing files'

    def stream(self, session, params=None):
        """stream(duration=None)

        **Process** - Generates example fake-files organized in the same way as
        they would be a regular smurf-stream. For end-to-end testing, we want
        an example of a pysmurf-ancilliary file, and then regular g3 that rotate
        at regular intervals. The content of the files here don't match what
        actual G3 or pysmurf files look like, however the directory structure
        is the same.

        Parameters:
            duration (float, optional):
                If set, will stop stream after specified amount of time (sec).
        """
        session.set_status('starting')
        action_time = time.time()
        files = ['freq.txt', 'mask.txt']
        for f in files:
            self._write_smurf_file(f, 'take_g3_stream',
                                   action_time=action_time)

        end_time = None
        if params.get('duration') is not None:
            end_time = time.time() + params['duration']

        self.streaming = True

        session.set_status('running')
        seq = 0
        sid = int(time.time())
        g3_file_info = None

        file_start = None
        while self.streaming:
            if g3_file_info is None:
                file_start = time.time()
                g3_file_info = {
                    'start': file_start,
                    'seq': seq,
                    'session_id': sid
                }

            time.sleep(1)

            if end_time is not None:
                if time.time() > end_time:
                    g3_file_info['stop'] = time.time()
                    self._write_g3_file(**g3_file_info)
                    break

            if time.time() - file_start > self.file_duration:
                g3_file_info['stop'] = time.time()
                self._write_g3_file(**g3_file_info)
                g3_file_info = None
                seq += 1

        if g3_file_info is not None:
            # Write out unwritten file info on stop
            g3_file_info['stop'] = time.time()
            self._write_g3_file(**g3_file_info)

        return True, "Finished stream"

    def _stop_stream(self, session, params=None):
        if self.streaming:
            session.set_status('stopping')
            self.streaming = False
            return True, 'requesting to stop taking data'
        else:
            return False, 'agent is not currently streaming'


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--stream-id', required=True,
                        help='Stream ID for fake smurf stream')
    pgroup.add_argument('--base-dir', required=True,
                        help="Base directory where data should be written")
    pgroup.add_argument('--file-duration', default=10*60, type=int,
                        help="Time in sec before rotating g3 files")

    return parser


if __name__ == '__main__':
    parser = make_parser()
    args = site_config.parse_args(agent_class='SmurfFileEmulator',
                                  parser=parser)

    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    agent, runner = ocs_agent.init_site_agent(args)

    file_em = SmurfFileEmulator(agent, args)
    agent.register_task('tune_dets', file_em.tune_dets)
    agent.register_task('take_iv', file_em.take_iv)
    agent.register_task('take_bias_steps', file_em.take_bias_steps)
    agent.register_task('bias_dets', file_em.bias_dets)
    agent.register_process('stream', file_em.stream, file_em._stop_stream)

    runner.run(agent, auto_reconnect=True)

