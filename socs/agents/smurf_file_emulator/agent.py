import argparse
import os
import time

import numpy as np
import so3g
import txaio
import yaml
from ocs import ocs_agent, site_config
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

primary_names = [
    'UnixTime', 'FluxRampIncrement', 'FluxRampOffset', 'Counter0',
    'Counter1', 'Counter2', 'AveragingResetBits', 'FrameCounter',
    'TESRelaySetting'
]
primary_idxs = {name: idx for idx, name in enumerate(primary_names)}


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

    def __init__(self, stream_id, sample_rate, tune,
                 action=None, action_time=None, quantize=True, drop_chance=0):
        self.frame_num = 0
        self.sample_num = 0
        self.session_id = int(time.time())
        self.tune = tune
        self.nchans = np.sum(tune.channels != -1)
        self.sample_rate = sample_rate
        self.stream_id = stream_id
        self.action = action
        self.action_time = action_time
        self.quantize = quantize
        self.drop_chance = drop_chance

    def tag_frame(self, fr):
        fr['frame_num'] = self.frame_num
        fr['session_id'] = self.session_id
        fr['sostream_id'] = self.stream_id
        fr['sostream_version'] = SOSTREAM_VERSION
        fr['time'] = core.G3Time(time.time() * core.G3Units.s)
        self.frame_num += 1
        return fr

    def get_obs_start_frame(self):
        fr = core.G3Frame(core.G3FrameType.Observation)
        fr['stream_placement'] = 'start'
        self.tag_frame(fr)
        return fr

    def get_obs_end_frame(self):
        fr = core.G3Frame(core.G3FrameType.Observation)
        fr['stream_placement'] = 'end'
        self.tag_frame(fr)
        return fr

    def get_status_frame(self, tag=''):
        fr = core.G3Frame(core.G3FrameType.Wiring)
        s = get_smurf_status()

        tune_key = 'AMCc.FpgaTopLevel.AppTop.AppCore.SysgenCryo.tuneFilePath'
        s[tune_key] = self.tune.tune_path

        tag_key = 'AMCc.SmurfProcessor.SOStream.stream_tag'
        s[tag_key] = tag

        m = self.tune.channels != -1
        chmask = self.tune.channels[m] + self.tune.bands[m] * CHANS_PER_BAND

        s['AMCc.SmurfProcessor.ChannelMapper.Mask'] = str(chmask.tolist())
        s['AMCc.SmurfProcessor.ChannelMapper.NumChannels'] = self.nchans.item()

        pysmurf_root = "AMCc.SmurfProcessor.SOStream"
        if self.action is not None:
            s[f'{pysmurf_root}.pysmurf_action'] = self.action
        if self.action_time is not None:
            s[f'{pysmurf_root}.pysmurf_action_timestamp'] = int(self.action_time)

        fr['status'] = yaml.dump(s)
        fr['dump'] = True
        self.tag_frame(fr)
        return fr

    def get_data_frame(self, start, stop):
        if self.quantize:
            # When "quantized", this clamps (start) and (stop) to integers so
            # timestamps created by np.arange are lined up when there's an
            # integer sample rate
            t0, t1 = int(start) - 1, int(stop) + 1
            nsamp = int((t1 - t0) * self.sample_rate)
            times = np.linspace(t0, t1, nsamp + 1, endpoint=True)
            m = (start <= times) & (times < stop)
            times = times[m]
        else:
            times = np.arange(start, stop, 1. / self.sample_rate)

        nsamps = len(times)
        frame_counter = np.arange(self.sample_num, self.sample_num + nsamps, dtype=int)
        self.sample_num += nsamps
        chans = np.arange(self.nchans)
        names = [f'r{ch:0>4}' for ch in chans]

        count_per_phi0 = 2**16
        data = np.zeros((self.nchans, nsamps), dtype=np.int32)
        data += count_per_phi0 * chans[:, None]
        data += (count_per_phi0 * 0.2 * np.sin(2 * np.pi * 8 * times)).astype(int)
        data += (count_per_phi0 * np.random.normal(0, 0.03, (self.nchans, nsamps))).astype(int)

        # Toss samples based on drop_chance
        m = self.drop_chance < np.random.uniform(0, 1, len(times))
        times = times[m]
        frame_counter = frame_counter[m]
        data = data[:, m]
        nsamps = len(times)

        fr = core.G3Frame(core.G3FrameType.Scan)

        g3times = core.G3VectorTime(times * core.G3Units.s)
        fr['data'] = so3g.G3SuperTimestream(names, g3times, data)

        primary_data = np.zeros((len(primary_names), nsamps), dtype=np.int64)
        primary_data[primary_idxs['UnixTime'], :] = (times * 1e9).astype(int)
        primary_data[primary_idxs['FrameCounter'], :] = frame_counter
        fr['primary'] = so3g.G3SuperTimestream(primary_names, g3times, primary_data)

        tes_bias_names = [f'bias{bg:0>2}' for bg in range(NBIASLINES)]
        bias_data = np.zeros((NBIASLINES, nsamps), dtype=np.int32)
        fr['tes_biases'] = so3g.G3SuperTimestream(tes_bias_names, g3times, bias_data)

        fr['timing_paradigm'] = 'Low Precision'
        fr['num_samples'] = nsamps

        self.tag_frame(fr)
        return fr


class DataStreamer:
    """
    Helper class for streaming G3 data
    """

    def __init__(self, stream_id, sample_rate, tune, timestreamdir,
                 file_duration, frame_len, action=None, action_time=None, drop_chance=0,
                 tag=''):
        self.frame_gen = G3FrameGenerator(stream_id, sample_rate, tune,
                                          action=action, action_time=action_time,
                                          drop_chance=drop_chance)

        self.session_id = self.frame_gen.session_id
        self.stream_id = stream_id
        self.timestreamdir = timestreamdir
        self.seq = 0
        self.file_duration = file_duration
        self.file_start = 0
        self.writer = None
        self.file_list = []
        self.frame_len = frame_len
        self.tag = tag
        self._last_stop = None

    def _get_g3_filename(self):
        """
        Returns the file path for a g3-file with specified session id and seq
        idx.
        """
        timecode = f"{self.session_id}"[:5]
        subdir = os.path.join(self.timestreamdir, timecode, self.stream_id)
        filepath = os.path.join(subdir, f"{self.session_id}_{self.seq:0>3}.g3")
        return filepath

    def _new_file(self):
        """
        Ends the current G3File (if one is open) and begins a new one,
        incrementing ``seq`` after updating.
        """
        self.end_file()
        fname = self._get_g3_filename()
        os.makedirs(os.path.dirname(fname), exist_ok=True)
        self.writer = core.G3Writer(fname)
        if self.seq == 0:
            self.writer(self.frame_gen.get_obs_start_frame())
            self.writer(self.frame_gen.get_status_frame(tag=self.tag))
        self.file_start = time.time()
        self.file_list.append(fname)
        self.seq += 1

    def end_file(self):
        """
        Ends the current file by sending a G3EndProcessing Frame.
        """
        if self.writer is not None:
            self.writer(self.frame_gen.get_obs_end_frame())
            self.writer(core.G3Frame(core.G3FrameType.EndProcessing))

    def write_next(self):
        """
        Writes the next data frame to disk. Will rotate files based on the
        current file start time and the file duration. This sleep wait
        for the frame-duration before writing the G3Frame to disk.
        """
        if self._last_stop is None:
            start = time.time()
        else:
            start = self._last_stop

        if (start - self.file_start > self.file_duration) or (self.writer is None):
            self._new_file()
        time.sleep(self.frame_len)
        stop = time.time()
        self._last_stop = stop
        self.writer(self.frame_gen.get_data_frame(start, stop))

    def stream_between(self, start, stop, wait=False):
        """
        This function will create a new observation and "stream" data between
        a specified start and stop time. This function will by default generate
        and write the data without sleeping for the specified amount of time.
        To avoid confusion, this will not rotate G3Files since that gets kind
        of complicated when you're not running in real time.

        Args
        ------
        start : float
            Start time of data
        stop : float
            Stop time of data
        wait : bool
            If True, will sleep for the correct amount of time between each
            written frame. Defaults to False.
        """
        frame_starts = np.arange(start, stop, self.frame_len)
        frame_stops = frame_starts + self.frame_len

        # In case there's already an open file
        self.seq = 0
        self.end_file()

        self._new_file()
        for t0, t1 in zip(frame_starts, frame_stops):
            if wait:
                now = time.time()
                if now < t1:
                    time.sleep(t1 - now)
            self.writer(self.frame_gen.get_data_frame(t0, t1))
        self.end_file()


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
        self.drop_chance = args.drop_chance

        self.streaming = False
        self.tune = None

    def _new_streamer(self, action=None, action_time=None, tag=''):
        return DataStreamer(
            self.stream_id, self.sample_rate, self.tune, self.timestreamdir,
            self.file_duration, self.frame_len,
            action=action, action_time=action_time, drop_chance=self.drop_chance,
            tag=tag
        )

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

    def _run_setup(self, action=None, action_time=None, session=None):
        """
        Helper function to run setup operations, used by uxm_setup and
        uxm_relock.
        """
        self.tune = Tune(nchans=self.nchans)

        if action is None:
            action = 'uxm_setup'
        if action_time is None:
            action_time = time.time()

        # Find Freq
        files = ['amp_sweep_freq.txt', 'amp_sweep_resonance.txt',
                 'amp_sweep_resp.txt']
        for f in files:
            self._write_smurf_file(f, action, action_time=action_time)

        # Setup Notches
        sdir = self._get_action_dir(action, action_time=action_time)
        self.tune.write_channel_assignments(basedir=sdir)
        self.tune.write_tune(basedir=sdir)

        # tracking setup
        action_time = time.time()
        fname = f"{int(time.time())}.dat"
        self._write_smurf_file(fname, action, action_time=action_time, prepend_ctime=False)

        # Short g3 stream
        streamer = self._new_streamer(action=action, action_time=action_time,
                                      tag='oper,noise')
        now = time.time()
        streamer.stream_between(now, now + 30, wait=False)
        if session is not None:
            session.data['noise_file'] = streamer.file_list[0]

    @ocs_agent.param('sleep', default=True)
    def uxm_setup(self, session, params):
        """uxm_setup(sleep=True)

        **Task** - Emulates files that might come from a general tune dets
        function. These are some of the files found on simons1 registered when
        running the following ops with a single band:

             1. Find-freq
             2. setup_notches
             3. tracking_setup
             4. short g3 stream

        Parameters:
            sleep (bool, optional):
                If True, will sleep for 1 sec after creating the tunefile,
                which is required for preventing filename collisions in
                end-to-end testing.
        """
        self._run_setup(action='uxm_setup', action_time=time.time(),
                        session=session)
        if params.get('sleep', True):
            time.sleep(1)
        return True, "Wrote tune files"

    @ocs_agent.param('tag', default=None)
    def take_noise(self, session, params=None):
        """take_noise(tag=None)

        **Task** - Takes a short noise timestream

        Parameters:
            tag (str, optional):
                User tag to add to the g3 stream.
        """
        action = 'take_noise'
        action_time = time.time()

        tag = 'oper,noise'
        if params.get('tag') is not None:
            tag += f',{params["tag"]}'

        streamer = self._new_streamer(action=action, action_time=action_time,
                                      tag=tag)
        now = time.time()
        streamer.stream_between(now, now + 30, wait=False)
        session.data['noise_file'] = streamer.file_list[0]
        time.sleep(1)
        return True, "Took noise data"

    def uxm_relock(self, session, params=None):
        """uxm_relock()

        **Task** - Normally this wouldn't involve a full find-freq, but for
        emulation purposes it's ok if this is the same as uxm_setup.
        """
        self._run_setup(action='uxm_relock', action_time=time.time(),
                        session=session)
        time.sleep(1)
        return True, "Wrote tune files"

    @ocs_agent.param('wait', default=True)
    @ocs_agent.param('tag', default=None)
    def take_iv(self, session, params=None):
        """take_iv(wait=True, tag=None)

        **Task** - Creates files generated associated with iv taking / analysis

        Parameters:
            wait (bool, optional):
                If true, will wait for the 5 seconds where fake IV data is
                generated
            tag (str, optional):
                User tag to add to the g3 stream.
        """
        action = 'take_iv'
        action_time = time.time()
        files = ['iv_analyze.npy', 'iv_bias_all.npy', 'iv_info.npy']

        tag = 'oper,iv'
        if params.get('tag') is not None:
            tag += f',{params["tag"]}'

        streamer = self._new_streamer(action=action, action_time=action_time,
                                      tag=tag)
        now = time.time()
        streamer.stream_between(now, now + 5, wait=params['wait'])

        for f in files:
            self._write_smurf_file(f, action, action_time=action_time)

        return True, "Wrote IV files"

    @ocs_agent.param('wait', default=True)
    @ocs_agent.param('tag', default=None)
    def take_bias_steps(self, session, params=None):
        """take_bias_steps(wait=True, tag=None)

        **Task** - Creates files associated with taking bias steps

        Parameters:
            wait (bool, optional):
                If true, will wait for the 5 seconds where fake data is
                generated
            tag (str, optional):
                User tag to add to the g3 stream.
        """
        action = 'take_bias_steps'
        action_time = time.time()
        files = ['bias_step_analysis.npy']

        tag = 'oper,bias_steps'
        if params.get('tag') is not None:
            tag += f',{params["tag"]}'

        streamer = self._new_streamer(action=action, action_time=action_time,
                                      tag=tag)
        now = time.time()
        streamer.stream_between(now, now + 5, wait=params['wait'])

        for f in files:
            self._write_smurf_file(f, action, action_time=action_time)

        return True, "Wrote Bias Step Files"

    @ocs_agent.param('wait', default=True)
    @ocs_agent.param('tag', default=None)
    def take_bgmap(self, session, params=None):
        """take_bgmap(wait=True, tag=None)

        **Task** - Creates files associated with taking a bias group mapping.

        Parameters:
            wait (bool, optional):
                If true, will wait for the 5 seconds where fake data is
                generated
            tag (str, optional):
                User tag to add to the g3 stream.
        """
        action = 'take_bgmap'
        action_time = time.time()

        tag = 'oper,bgmap'
        if params.get('tag') is not None:
            tag += f',{params["tag"]}'

        streamer = self._new_streamer(action=action, action_time=action_time,
                                      tag=tag)
        now = time.time()
        streamer.stream_between(now, now + 5, wait=params['wait'])

        files = ['bg_map.npy', 'bias_step_analysis.npy']
        for f in files:
            self._write_smurf_file(f, action, action_time=action_time)

        return True, "Finished taking bgmap"

    def bias_dets(self, session, params=None):
        """bias_dets()

        **Task** - Creates files associated with biasing dets, which is none.
        """
        time.sleep(1)
        return True, 'Wrote det biasing files'

    @ocs_agent.param('duration', default=None)
    @ocs_agent.param('use_stream_between', default=False, type=bool)
    @ocs_agent.param('start_offset', default=0, type=float)
    @ocs_agent.param('tag', default=None)
    def stream(self, session, params):
        """stream(duration=None, use_stream_between=False, start_offset=0, tag=None)

        **Process** - Generates example fake-files organized in the same way as
        they would be a regular smurf-stream. For end-to-end testing, we want
        an example of a pysmurf-ancilliary file, and then regular g3 that rotate
        at regular intervals. The content of the files here don't match what
        actual G3 or pysmurf files look like, however the directory structure
        is the same.

        Parameters:
            duration (float, optional):
                If set, will stop stream after specified amount of time (sec).
            use_stream_between (bool, optional):
                If True, will use the DataStreamer's `stream_between` function
                instead of writing frames one at a time. This allows you to write
                an entire timestream for the specified duration without waiting.
            start_offset (float, optional):
                If set, this will add an offset to the start time passed to the
                `stream_between` function, allowing you to create offsets between
                streams taken at the same time.
            tag (str, optional):
                User tag to add to the g3 stream.
        """

        if self.tune is None:
            raise ValueError("No tune loaded!")

        # Write initial smurf metadata
        if 'duration' in params:
            action = 'take_g3_data'
        else:
            action = 'stream_g3_on'

        action_time = time.time()
        files = ['freq.txt', 'mask.txt']
        for f in files:
            self._write_smurf_file(f, action, action_time=action_time)

        start_time = time.time() + params['start_offset']
        end_time = None
        if params.get('duration') is not None:
            end_time = start_time + params['duration']

        tag = 'obs,cmb'
        if params.get('tag') is not None:
            tag += f',{params["tag"]}'

        streamer = self._new_streamer(action=action, action_time=action_time, tag='obs,cmb')
        session.data['session_id'] = streamer.session_id
        session.data['g3_files'] = streamer.file_list

        if params['use_stream_between']:
            streamer.stream_between(start_time, end_time)
            return True, "Finished Stream"

        self.streaming = True
        while self.streaming:
            streamer.write_next()

            if end_time is not None:
                if time.time() > end_time:
                    break

        streamer.end_file()

        time.sleep(1)
        return True, "Finished Stream"

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
    pgroup.add_argument('--drop-chance', default=0, type=float,
                        help="Fractional chance to drop samples")

    return parser


def main(args=None):
    parser = make_parser()
    args = site_config.parse_args(agent_class='SmurfFileEmulator',
                                  parser=parser,
                                  args=args)

    txaio.start_logging(level=os.environ.get('LOGLEVEL', 'info'))

    agent, runner = ocs_agent.init_site_agent(args)

    file_em = SmurfFileEmulator(agent, args)
    agent.register_task('uxm_setup', file_em.uxm_setup)
    agent.register_task('uxm_relock', file_em.uxm_relock)
    agent.register_task('take_iv', file_em.take_iv)
    agent.register_task('take_bias_steps', file_em.take_bias_steps)
    agent.register_task('take_bgmap', file_em.take_bgmap)
    agent.register_task('bias_dets', file_em.bias_dets)
    agent.register_task('take_noise', file_em.take_noise)
    agent.register_process('stream', file_em.stream, file_em._stop_stream)

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
