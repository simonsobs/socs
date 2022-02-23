import argparse
import so3g
from spt3g import core
import txaio
import os
import numpy as np
import yaml
import ast
from scipy import signal
import queue
import time
import pandas as pd
ON_RTD = os.environ.get('READTHEDOCS') == 'True'

if not ON_RTD:
    from ocs import ocs_agent, site_config


# This will be populated when the first frame comes in
primary_idxs = {}


def load_frame_data(frame):
    """
    Returns detector data from a G3Stream.

    Returns:
        times : np.ndarray
            Array with shape (nsamps) of timestamps (sec)
        data : np.ndarray
            Array with shape (nchans, nsamps) of detector phase data (phi0)
    """
    primary = frame['primary']
    if isinstance(primary, core.G3TimesampleMap):
        times = np.array(primary['UnixTime']) / 1e9
    else:
        if not primary_idxs:
            for i, name in enumerate(frame['primary'].names):
                primary_idxs[name] = i
        times = np.array(primary.data[primary_idxs['UnixTime']]) / 1e9

    d = frame['data']
    if isinstance(d, core.G3TimestreamMap):
        nchans, nsamps = len(d), d.n_samples
        data = np.ndarray((nchans, nsamps), dtype=np.float32)
        for i in range(nchans):
            data[i] = d[f'r{i:0>4}'] * (2*np.pi) / 2**16

    else:  # G3SuperTimestream probably
        data = d.data * (2*np.pi) / 2**16

    return times, data


class FIRFilter:
    """
    Class for Finite Input Response filter. Filter phases are preserved between
    `lfilt` calls so you can filter frame-based data.
    """
    def __init__(self, b, a, nchans=None):
        if nchans is None:
            nchans = 4096
        self.b = b
        self.a = a
        self.z = np.zeros((nchans, len(b)-1))

    def lfilt(self, data):
        """Filters data in place"""
        n = len(data)
        data[:, :], self.z[:n] = signal.lfilter(self.b, self.a, data, axis=1,)

    @classmethod
    def butter_highpass(cls, cutoff, fs, order=5):
        """
        Creates an highpass butterworth FIR filter

        Args
        ----
        cutoff : float
            Cutoff freq (Hz)
        fs : float
            sample frequency (Hz)
        order : int
            Order of the filter
        """
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='high', analog=False)
        return cls(b, a)

    @classmethod
    def butter_lowpass(cls, cutoff, fs, order=5):
        """
        Creates an lowpass butterworth FIR filter

        Args
        ----
        cutoff : float
            Cutoff freq (Hz)
        fs : float
            sample frequency (Hz)
        order : int
            Order of the filter
        """
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='low', analog=False)
        return cls(b, a)


class RollingAvg:
    """
    Class for calculating rolling averages across multiple frames. Useful
    for simple filtering and calculating the rms.

    Args
    -----
        N (int):
            Number of samples to average together
        nchans (int):
            Number of channels this will be operating on.
    """
    def __init__(self, N, nchans):
        self.N = N
        self.nchans = nchans
        self.rollover = np.zeros((nchans, N))

    def apply(self, data):
        """
        Apply rolling avg to data array.

        Args
        -----
            data (np.ndarray):
                Array of data. Must be of shape (nchans, nsamps)
        """
        nsamps = data.shape[1]
        summed = 1./self.N * np.cumsum(
            np.concatenate((self.rollover, data), axis=1), axis=1)
        if self.N <= nsamps:
            # Replace entire rollover array
            self.rollover = data[:, -self.N:]
        else:
            # Roll back and just update with samples available
            self.rollover = np.roll(self.rollover, -nsamps)
            self.rollover[:, -nsamps:] = data[:, :]

        print(data.shape, (summed[:, self.N:] - summed[:, :-self.N]).shape)


        return summed[:, self.N:] - summed[:, :-self.N]



class FocalplaneConfig:
    def __init__(self):
        """
        Object to configure the focal-plane layout.

        Attributes
        -------------
        chan_mask : np.ndarray
            Map from absolute_smurf_chan --> Visual Element index
        """
        self.num_dets = 0
        self.xs = []
        self.ys = []
        self.rots = []
        self.cnames = []
        self.templates = []
        self.value_names = []
        self.eqs = []
        self.eq_labels = []
        self.eq_color_is_dynamic = []
        self.cmaps = []
        self.chan_mask = np.full(4096, -1)

    def config_frame(self):
        frame = core.G3Frame(core.G3FrameType.Wiring)
        frame['x'] = core.G3VectorDouble(self.xs)
        frame['y'] = core.G3VectorDouble(self.ys)
        frame['cname'] = core.G3VectorString(self.cnames)
        frame['rotation'] = core.G3VectorDouble(self.rots)
        frame['templates'] = core.G3VectorString(self.templates)
        frame['values'] = core.G3VectorString(self.value_names)
        frame['color_is_dynamic'] = core.G3VectorBool(self.eq_color_is_dynamic)
        frame['equations'] = core.G3VectorString(self.eqs)
        frame['eq_labels'] = core.G3VectorString(self.eq_labels)
        frame['cmaps'] = core.G3VectorString(self.cmaps)
        return frame
        
    def add_vis_elem(self, name, x, y, rot, value_names, eqs, eq_labels, cmaps,
                     template, abs_smurf_chan, eq_color_is_dynamic):
        self.cnames.append(name)
        self.xs.append(float(x))
        self.ys.append(float(y))
        self.rots.append(rot)
        self.templates.append(template)
        self.value_names.extend(value_names)
        self.cmaps.extend(cmaps)
        self.eqs.extend(eqs)
        self.eq_labels.extend(eq_labels)
        self.eq_color_is_dynamic.extend(eq_color_is_dynamic)
        self.chan_mask[abs_smurf_chan] = self.num_dets
        self.num_dets += 1

    @classmethod
    def grid(cls, xdim, ydim, ygap=0):
        fp = cls()
        xs, ys = np.arange(xdim), np.arange(ydim)

        # Adds gaps every ygap rows
        if ygap > 0:
            ys = ys + 0.5 * ys // ygap

        template = 'box'
        cmaps = ['red_cmap', 'blue_cmap']
        eq_color_is_dynamic = [True, False]
        for i in range(xdim * ydim):
            x, y = xs[i % xdim], ys[i // xdim]
            name = f"channel_{i}"
            value_names = [f'{name}/raw', f'{name}/rms']
            eqs = [f'{name}/raw', f'* {name}/rms rms_scale']
            eq_labels = ['raw', 'rms']
            fp.add_vis_elem(name, x, y, 0, value_names, eqs, eq_labels, cmaps,
                            template, i, eq_color_is_dynamic)

        return fp

    @classmethod
    def from_csv(cls, csv_file, wafer_scale=1.):
        fp = cls()
        df = pd.read_csv(csv_file)
        cmaps = {
            90: ['red_cmap', 'blue_cmap'],
            150: ['blue_cmap', 'red_cmap']
        }
        templates = {
            'A': "template_c0_p0",
            'B': "template_c0_p1",
        }

        for i, row in df.iterrows():
            try:
                bandpass = int(row['bandpass'])
                template = templates[row['pol']]
            except ValueError:
                continue
            abs_chan = row['smurf_band'] * 512 + row['smurf_channel']
            x, y = row['det_x'] * wafer_scale, row['det_y'] * wafer_scale

            name = f"det_{i}"
            eqs = [f'{name}/raw', f'* {name}/rms rms_scale']

            fp.add_vis_elem(
                name, x, y, 0, cmaps[bandpass], eqs, template, abs_chan
            )

        return fp


class MagpieAgent:
    mask_register = 'AMCc.SmurfProcessor.ChannelMapper.Mask'

    def __init__(self, agent, args):
        self.agent = agent
        self.log = self.agent.log
        self._running = False

        self.target_rate = args.target_rate
        layout = args.layout.lower()
        if layout == 'grid':
            self.fp = FocalplaneConfig.grid(
                args.xdim, args.ydim, ygap=8
            )
        elif layout == 'wafer':
            if args.csv_file is not None:
                self.fp = FocalplaneConfig.from_csv(
                    args.csv_file, wafer_scale=args.wafer_scale
                )

        self.sent_cfg = False
        self.num_dets = self.fp.num_dets
        self.mask = np.arange(4096)

        self.reader = core.G3Reader(args.src)
        self.sender = core.G3NetworkSender(
            hostname='*', port=args.dest, max_queue_size=1000
        )

        self.out_queue = queue.Queue()
        self.delay = 0

        self.lowpass = FIRFilter.butter_lowpass(
            self.target_rate, self.target_rate * 2 + 1, order=4)
        self.send_config_flag = True

        self.avg1, self.avg2 = None, None

    def set_target_rate(self, session, params=None):
        """
        Sets the target downsampled sample-rate of the data sent to lyrebird

        Args:
            target_rate : float
                Target sample rate for lyrebird (Hz)
        """
        if params is None:
            params = {}
        self.target_rate = params['target_rate']
        return True, f'Set target rate to {self.target_rate}'

    def process_status(self, frame):
        """
        Processes a status frame.
        """
        if 'session_id' not in frame:
            return
        if self.mask_register in frame['status']:
            status = yaml.safe_load(frame['status'])
            self.mask = np.array(
                ast.literal_eval(status[self.mask_register])
            )

    def process_data(self, frame):
        """
        Processes a Scan frame. If lyrebird is enabled, this will return a seq
        of G3Frames that are formatted for lyrebird to ingest.
        """
        if 'session_id' not in frame:
            return []

        # Calculate downsample factor
        times_in, data_in = load_frame_data(frame)
        sample_rate = 1./np.median(np.diff(times_in))
        nsamps = len(times_in)
        nchans = len(data_in)

        if self.avg1 is None:
            self.avg1 = RollingAvg(200, nchans)
            self.avg2 = RollingAvg(200, nchans)
        elif self.avg1.nchans != nchans:
            self.log.warn(f"Channel count has changed! {self.avg1.nchans}->{nchans}")
            self.avg1 = RollingAvg(200, nchans)
            self.avg2 = RollingAvg(200, nchans)

        # Calc RMS
        hpf_data = data_in - self.avg1.apply(data_in)  # To high-pass filter
        rms = np.sqrt(self.avg2.apply(hpf_data**2))  # To calc rolling rms

        ds_factor = sample_rate // self.target_rate
        if np.isnan(ds_factor):  # There is only one element in the timestream
            ds_factor = 1
        ds_factor = max(int(ds_factor), 1)  # Prevents downsample factors < 1

        # Arrange output data structure
        sample_idxs = np.arange(0, nsamps, ds_factor, dtype=np.int32)
        num_frames = len(sample_idxs)

        data_out = np.zeros((num_frames, np.max(self.fp.chan_mask)+1))
        rms_out = np.zeros((num_frames, np.max(self.fp.chan_mask)+1))
        times_out = times_in[sample_idxs]

        abs_chans = self.mask[np.arange(nchans)]
        data_idxs = np.full(2*nchans, -1)
        raw_out = np.zeros((num_frames, np.max(self.fp.chan_mask)))
        rms_out = np.zeros((num_frames, np.max(self.fp.chan_mask)))
        for i, c in enumerate(abs_chans):
            if c >= len(self.fp.chan_mask):
                continue
            idx = self.fp.chan_mask[c]
            if idx >= 0:
                raw_out[:, idx] = data_in[i, sample_idxs]
                rms_out[:, idx] = rms[i, sample_idxs]

        out = []
        for i in range(num_frames):
            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['idx'] = 0
            fr['data'] = core.G3VectorDouble(raw_out[i])
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            out.append(fr)

            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['idx'] = 1
            fr['data'] = core.G3VectorDouble(rms_out[i])
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            out.append(fr)
        return out


    def process(self, session, params=None):
        self._running = True
        session.set_status('running')

        while self._running:
            if self.send_config_flag:
                self.sender.Process(self.fp.config_frame())
                self.send_config_flag = False

            frame = self.reader.Process(None)[0]
            if frame.type == core.G3FrameType.Wiring:
                self.process_status(frame)
                continue
            elif frame.type == core.G3FrameType.Scan:
                out = self.process_data(frame)
            else:
                continue
            for f in out:
                self.out_queue.put(f)
        return True, "Stopped run process"

    def _process_stop(self, session, params=None):
        self._running = False
        return True, "Stopping run process"

    def send(self, session, params=None):
        self._send_running = True
        session.set_status('running')

        first_frame_time = None
        stream_start_time = None
        self.delay = 5
        while self._send_running:
            f = self.out_queue.get(block=True)
            t = f['timestamp'].time / core.G3Units.s
            now = time.time()
            if first_frame_time is None:
                first_frame_time = t
                stream_start_time = now

            this_frame_time = stream_start_time + (t - first_frame_time) + self.delay
            if this_frame_time > now:
                time.sleep(this_frame_time - now)
            self.sender.Process(f)

        return True, "Stopped send process"


    def _send_stop(self, session, params=None):
        self._send_running = False
        return True, "Stopping send process"



def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    parser.add_argument('--src', default='tcp://localhost:4532',
                        help="Address of incoming G3Frames.")
    parser.add_argument('--dest', type=int, default=8675,
                        help="Port to server lyrebird frames")
    parser.add_argument('--target-rate', '-t', type=float, default=200)
    parser.add_argument('--layout', '-l', default='grid', choices=['grid', 'wafer'],
                        help="Focal plane layout style")
    parser.add_argument('--xdim', type=int, default=64,
                        help="Number of pixesl in x-dimension for grid layout")
    parser.add_argument('--ydim', type=int, default=64,
                        help="Number of pixesl in y-dimension for grid layout")
    parser.add_argument('--wafer-scale', '--ws', type=float, default=50.,
                        help="scale of wafer coordinates")
    parser.add_argument('--csv-file', type=str, help="Detmap CSV file")
    return parser


if __name__ == '__main__':
    txaio.use_twisted()
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))
    parser = make_parser()
    args = site_config.parse_args(agent_class='MagpieAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    magpie = MagpieAgent(agent, args)

    agent.register_process('process', magpie.process, magpie._process_stop, startup=True)
    agent.register_process('send', magpie.send, magpie._send_stop, startup=True)
    agent.register_task('set_target_rate', magpie.set_target_rate)

    runner.run(agent, auto_reconnect=True)
