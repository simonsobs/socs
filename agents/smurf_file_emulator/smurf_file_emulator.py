import time
import os
import argparse
import txaio
import numpy as np

from ocs import ocs_agent, site_config
import yaml

import so3g
from spt3g import core


def get_smurf_status():
    """Loads a sample status dict from file"""
    status_file = os.path.join(os.path.split(__file__)[0], 'status_sample.yaml')
    with open(status_file, 'r') as f:
        return yaml.safe_load(f)


SOSTREAM_VERSION = 2
NBIASLINES = 16
NBANDS = 8
# Range of frequencies allowed by smurf
SMURF_FREQ_RANGE = (4e3, 8e3)
SUBBANDS_PER_BAND = 512
CHANS_PER_BAND = 512

class Tune:
    """
    Helper class for generating tunes
    """
    def __init__(self, nchans=1720):
        self.log = txaio.make_logger()

        self.nchans = nchans
        self.res_freqs = np.linspace(*SMURF_FREQ_RANGE, nchans, endpoint=False)

        band_width = (SMURF_FREQ_RANGE[1] - SMURF_FREQ_RANGE[0]) / NBANDS
        subband_width = band_width / SUBBANDS_PER_BAND

        rs = self.res_freqs - SMURF_FREQ_RANGE[0]
        self.bands = (rs / band_width).astype(int)
        self.subbands = ((rs / subband_width) % SUBBANDS_PER_BAND).astype(int) 

        # just assigns channels in order for each band, making sure this
        # doesn't go above chans_per_band
        self.channels = np.full(nchans, -1, dtype=int)
        for b in np.unique(self.bands):
            m = self.bands == b
            self.channels[m] = np.arange(np.sum(m))
        self.channels[self.channels >= CHANS_PER_BAND] = -1

        self.assignment_files = [None for _ in range(NBANDS)]

    def encode_band(self, band):
        """
        Encodes band-information in the format of pysmurf tunefiles. This
        has the same structure as pysmurf tunefiles, but contains just enough
        information for indexing.
        """
        d = {
            'lock_status': {},
            'find_freq': {
                'resonance': self.res_freqs,
            },
            'tone_power': 12,
            'resonances': {}
        }

        for i, f in enumerate(self.res_freqs[self.bands == band]):
            d['resonances'][i] = {'freq': f}

        if self.assignment_files[band] is not None:
            d['channel_assignment'] = self.assignment_files[band]

        return d

    def encode_tune(self):
        """
        Encodes a full tune dictionary in the format of pysmurf tunefiles.
        """
        return {
            b: self.encode_band(b)
            for b in np.unique(self.bands)
        }

    def write_tune(self, basedir=''):
        """
        Writes tune to disk.

        Args
        ----
        basedir : str
            Directory where tune should be written.
        """
        timestamp = int(time.time())

        path = os.path.join(basedir, f'{timestamp}_tune.npy')
        np.save(path, self.encode_tune(), allow_pickle=True)
        self.tune_path = path
        self.log.debug(f"Writing tune: {self.tune_path}")
        return path

    def write_channel_assignments(self, bands=None, basedir=''):
        """
        Writes channel assignment files to disk.

        Args
        -----
        bands : optional, int, list[int]
            Bands to write to disk. Defaults to all that are present in the
            tune.
        basedir : str
            Directory where files should be written
        """
        if bands is None:
            bands = np.unique(self.bands)
        bands = np.atleast_1d(bands)

        timestamp = int(time.time())

        for b in bands:
            path = os.path.join(
                basedir, f'{timestamp}_channel_assignment_b{b}.txt'
            )
            m = self.bands == b
            d = np.array([
                self.res_freqs[m],
                self.subbands[m], 
                self.channels[m],
                np.full(np.sum(m), -1)
            ]).T
            np.savetxt(path, d, fmt='%.4f,%d,%d,%d')
            self.assignment_files[b] = path


class G3FrameGenerator:
    """
    Helper class for generating G3 Streams.
    """

    def __init__(self, stream_id, sample_rate, tune):
        self.frame_num = 0
        self.session_id = int(time.time())
        self.tune = tune
        self.nchans = np.sum(tune.channels != -1)
        self.sample_rate = sample_rate
        self.stream_id = stream_id

    def tag_frame(self, fr):
        fr['frame_num'] = self.frame_num
        fr['session_id'] = self.session_id
        fr['sostream_id'] = self.stream_id
        fr['sostream_version'] = SOSTREAM_VERSION
        fr['time'] = core.G3Time(time.time() * core.G3Units.s)
        self.frame_num += 1
        return fr

    def get_obs_frame(self):
        fr = core.G3Frame(core.G3FrameType.Observation)
        self.tag_frame(fr)
        return fr

    def get_status_frame(self):
        fr = core.G3Frame(core.G3FrameType.Wiring)
        s = get_smurf_status()

        tune_key = 'AMCc.FpgaTopLevel.AppTop.AppCore.SysgenCryo.tuneFilePath'
        s[tune_key] = self.tune.tune_path

        m = self.tune.channels != -1
        chmask = self.tune.channels[m] + self.tune.bands[m] * CHANS_PER_BAND

        s['AMCc.SmurfProcessor.ChannelMapper.Mask'] = str(chmask.tolist())
        s['AMCc.SmurfProcessor.ChannelMapper.NumChannels'] = self.nchans.item()

        fr['status'] = yaml.dump(s)
        fr['dump'] = True
        self.tag_frame(fr)
        return fr

    def get_data_frame(self, start, stop):

        times = np.arange(start, stop, 1. / self.sample_rate)
        nsamps = len(times)
        chans = np.arange(self.nchans)
        names = [f'r{ch:0>4}' for ch in chans]

        count_per_phi0 = 2**16
        data = np.zeros((self.nchans, nsamps), dtype=np.int32)
        data += count_per_phi0 * chans[:, None]
        data += (count_per_phi0 * 0.2 * np.sin(2 * np.pi * 8 * times)).astype(int)
        data += (count_per_phi0 * np.random.normal(0, 0.03, (self.nchans, nsamps))).astype(int)

        fr = core.G3Frame(core.G3FrameType.Scan)

        g3times = core.G3VectorTime(times * core.G3Units.s)
        fr['data'] = so3g.G3SuperTimestream(names, g3times, data)

        primary_names = [
            'UnixTime', 'FluxRampIncrement', 'FluxRampOffset', 'Counter0',
            'Counter1', 'Counter2', 'AveragingResetBits', 'FrameCounter',
            'TESRelaySetting'
        ]
        primary_data = np.zeros((len(primary_names), nsamps), dtype=np.int64)
        primary_data[0, :] = (times * 1e9).astype(int)
        fr['primary'] = so3g.G3SuperTimestream(primary_names, g3times, primary_data)

        tes_bias_names = [f'bias{bg:0>2}' for bg in range(NBIASLINES)]
        bias_data = np.zeros((NBIASLINES, nsamps), dtype=np.int32)
        fr['tes_biases'] = so3g.G3SuperTimestream(tes_bias_names, g3times, bias_data)

        fr['timing_paradigm'] = 'Low Precision'
        fr['num_samples'] = nsamps

        self.tag_frame(fr)
        return fr


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
        self.nchans = args.nchans
        self.sample_rate = args.sample_rate
        self.frame_len = args.frame_len

        self.streaming = False
        self.tune = None

    def _get_g3_filename(self, session_id, seq, makedirs=True):
        """
        Returns the file path for a g3-file with specified session id and seq
        idx.
        """
        timecode = f"{session_id}"[:5]
        subdir = os.path.join(self.timestreamdir, timecode, self.stream_id)
        filepath = os.path.join(subdir, f"{session_id}_{seq:0>3}.g3")
        return filepath

    def _get_action_dir(self, action, action_time=None, is_plot=False):
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
        return subdir

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
        subdir = self._get_action_dir(
            action, action_time=action_time, is_plot=is_plot
        )
        if prepend_ctime:
            filepath = os.path.join(subdir, f'{t}_{name}')
        else:
            filepath = os.path.join(subdir, name)
        self.log.info(f"Writing smurf file: {filepath}")
        with open(filepath, 'w') as f:
            f.write(f'start: {time.time()}\n')
        return filepath

    @ocs_agent.param('test_mode', type=bool, default=False)
    def tune_dets(self, session, params):
        """tune_dets()

        **Task** - Emulates files that might come from a general tune dets
        function. These are some of the files found on simons1 registered when
        running the following ops with a single band:

             1. Find-freq
             2. setup_notches
             3. tracking_setup
             4. short g3 stream

        Args
        ----
        test_mode : bool
            If True, will skip any wait times associated with writing
            g3 files.
        """
        self.tune = Tune(nchans=self.nchans)

        # Find Freq
        action_time = time.time()
        files = ['amp_sweep_freq.txt', 'amp_sweep_resonance.txt',
                 'amp_sweep_resp.txt']
        for f in files:
            self._write_smurf_file(f, 'find_freq',
                                   action_time=action_time)

        # Setup Notches
        sdir = self._get_action_dir('setup_notches')
        self.tune.write_channel_assignments(basedir=sdir)
        self.tune.write_tune(basedir=sdir)

        # tracking setup
        action_time = time.time()
        fname = f"{int(time.time())}.dat"
        self._write_smurf_file(fname, 'tracking_setup', prepend_ctime=False)

        # Short g3 stream
        frame_gen = G3FrameGenerator(
            self.stream_id, self.sample_rate, self.tune
        )
        fname = self._get_g3_filename(frame_gen.session_id, 0, makedirs=True)
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        session.data['noise_file'] = fname
        writer = core.G3Writer(fname)
        writer(frame_gen.get_obs_frame())
        writer(frame_gen.get_status_frame())
        start = time.time()
        stop = start + 30
        frame_starts = np.arange(start, stop, self.frame_len)
        frame_stops = frame_starts + self.frame_len
        for t0, t1 in zip(frame_starts, frame_stops):
            if not params['test_mode']:
                now = time.time()
                if now < t1:
                    time.sleep(t1 - now)
            writer(frame_gen.get_data_frame(t0, t1))
        writer(core.G3Frame(core.G3FrameType.EndProcessing))

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

    @ocs_agent.param('duration', default=None)
    def stream(self, session, params):
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

        if self.tune is None:
            raise ValueError("No tune loaded!")

        # Write initial smurf metadata
        action_time = time.time()
        files = ['freq.txt', 'mask.txt']
        for f in files:
            self._write_smurf_file(f, 'take_g3_stream',
                                   action_time=action_time)

        end_time = None
        if params.get('duration') is not None:
            end_time = time.time() + params['duration']

        session.set_status('running')
        frame_gen = G3FrameGenerator(
            self.stream_id, self.sample_rate, self.tune
        )
        session.data['session_id'] = frame_gen.session_id
        session.data['g3_files'] = []

        seq = 0
        fname = self._get_g3_filename(frame_gen.session_id, seq, makedirs=True)
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        session.data['g3_files'].append(fname)
        writer = core.G3Writer(fname)
        file_start = time.time()

        writer(frame_gen.get_obs_frame())
        writer(frame_gen.get_status_frame())
        self.streaming = True
        while self.streaming:
            start = time.time()
            time.sleep(self.frame_len)
            stop = time.time()
            writer(frame_gen.get_data_frame(start, stop))

            if end_time is not None:
                if stop > end_time:
                    break

            if time.time() - file_start > self.file_duration:
                writer(core.G3Frame(core.G3FrameType.EndProcessing))
                seq += 1
                fname = self._get_g3_filename(
                    frame_gen.session_id, seq, makedirs=True
                )
                os.makedirs(os.path.dirname(fname), exist_ok=True)
                session.data['g3_files'].append(fname)
                writer = core.G3Writer(fname)
                file_start = time.time()

        writer(core.G3Frame(core.G3FrameType.EndProcessing))

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
    pgroup.add_argument('--file-duration', default=10 * 60, type=float,
                        help="Time in sec before rotating g3 files")
    pgroup.add_argument('--nchans', default=1024, type=int,
                        help="Number of channels to stream from")
    pgroup.add_argument('--sample-rate', default=200, type=float,
                        help="Sample rate for streaming data")
    pgroup.add_argument('--frame-len', default=2, type=float,
                        help="Time per G3 data frame (seconds)")

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
