import time
import os
import argparse
import warnings
import txaio

from typing import Optional

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
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

    def _write_smurf_file(self, name, action, action_time=None):
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
            action_time = int(t)
        timecode = f"{action_time}"[:5]
        subdir = os.path.join(
            self.smurfdir, timecode, self.stream_id, f'{action_time}_{action}'
        )
        os.makedirs(subdir, exist_ok=True)
        filepath = os.path.join(subdir, f'{t}_{name}')
        self.log.info(f"Writing smurf file: {filepath}")
        with open(filepath, 'w') as f:
            f.write(f'start: {time.time()}\n')


    @ocs_agent.param('nchans', type=int, default=4096)
    @ocs_agent.param('sample_rate', type=float, default=400.)
    def stream(self, session, params=None):
        """stream(nchans=4096, sample_rate=400)

        **Process** - Generates example fake-files organized in the same way as
        they would be a regular smurf-stream. For end-to-end testing, we want
        an example of a pysmurf-ancilliary file, and then regular g3 that rotate
        at regular intervals. The content of the files here don't match what
        actual G3 or pysmurf files look like, however the directory structure
        is the same.

        The pysmurf file is a fake IV file created at the start of the stream
        containing just the file creation time. The G3 files are rotated at
        the time specified in the site-config (with 10 min as the default).
        The files contain valid yaml and specify the file start time, the file
        end time, the number of channels, and the number of samples, which are
        determined by the ``nchans`` and ``sample_rate`` params.

        Parameters:
            nchans (int, optional):
                Number of chans in the stream. This is written into the g3
                files but effects nothing else. Defaults to 4096.
            sample_rate (float, optional):
                Sample rate of the "data". This effects the ``nsamps`` that is
                saved in the file's yaml, but nothing else.
        """
        session.set_status('starting')

        self.streaming = True

        # Writes IV file
        self._write_smurf_file("IV.npy", 'take_IV')

        session_id = int(time.time())
        seq = 0
        timecode = f"{session_id}"[:5]
        subdir = os.path.join(self.timestreamdir, timecode, self.stream_id)
        os.makedirs(subdir, exist_ok=True)
        session.set_status('running')
        while self.streaming:
            filepath = os.path.join( subdir, f"{session_id}_{seq:0>3}.g3")
            file_start = time.time()
            time.sleep(self.file_duration)
            file_stop = time.time()
            nsamps = int(params['sample_rate'] * (file_stop - file_start))
            self.log.info(f"Writing file {filepath}")
            with open(filepath, 'w') as f:
                f.write(f'start: {file_start}\n')
                f.write(f"stop: {file_stop}\n")
                f.write(f"nchans: {params['nchans']}\n")
                f.write(f"nsamps: {nsamps}\n")
            seq += 1

    def _stop_stream(self, session, params=None):
        if self.streaming:
            session.set_status('stopping')
            self.streaming= False
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
    pgroup.add_argument("--stream-on-start", action='store_true',
                        help="If true, will stream data on startup")
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
    agent.register_process(
        'stream', file_em.stream, file_em._stop_stream,
        startup=args.stream_on_start
    )

    runner.run(agent, auto_reconnect=True)

