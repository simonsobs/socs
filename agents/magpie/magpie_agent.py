import argparse
from spt3g import core
import so3g
import txaio
import os
import numpy as np
import yaml
import ast
from scipy import signal
import queue
import time
ON_RTD = os.environ.get('READTHEDOCS') == 'True'

if not ON_RTD:
    from ocs import ocs_agent, site_config


# This will be populated when the first frame comes in
primary_idxs = {}

def load_frame_data(frame):
    if len(primary_idxs) == 0:
        for i, name in enumerate(frame['primary'].names):
            primary_idxs[name] = i

    times = np.array(frame['primary'].data[primary_idxs['UnixTime']]) / 1e9
    data = frame['data'].data

    return times, data



class FIRFilter:
    def __init__(self, b, a, nchans=None):
        if nchans is None:
            nchans = 4096
        self.b = b
        self.a = a
        self.z = np.zeros((nchans, len(b)-1))

    def lfilt(self, data):
        """Filters data in place"""
        n = len(data)
        data[:, :], self.z[:n] = signal.lfilter(self.b, self.a, data, axis=1, zi=self.z[:n])

    @classmethod
    def butter_highpass(cls, cutoff, fs, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='high', analog=False)
        return cls(b, a)

    @classmethod
    def butter_lowpass(cls, cutoff, fs, order=5):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='low', analog=False)
        return cls(b, a)


class FocalplaneConfig:
    def __init__(self, ndets=0):
        self.num_dets = ndets
        self.xs = [0 for _ in range(ndets)]
        self.ys = [0. for _ in range(ndets)]
        self.rots = [0. for _ in range(ndets)]
        self.cnames = ['' for _ in range(ndets)]
        self.eqs = ['' for _ in range(ndets)]
        self.cmaps = ['' for _ in range(ndets)]
        self.templates = ['' for _ in range(ndets)]

        self.chan_mask = np.arange(ndets)

    def config_frame(self):
        frame = core.G3Frame(core.G3FrameType.Wiring)
        frame['x'] = core.G3VectorDouble(self.xs)
        frame['y'] = core.G3VectorDouble(self.ys)
        frame['rotation'] = core.G3VectorDouble(self.rots)
        frame['cname'] = core.G3VectorString(self.cnames)
        frame['equations'] = core.G3VectorString(self.eqs)
        frame['cmaps'] = core.G3VectorString(self.cmaps)
        frame['templates'] = core.G3VectorString(self.templates)
        return frame

    @classmethod
    def grid(cls, xdim, ydim, ygap=0):
        fp = cls()
        xs, ys = range(xdim), range(ydim)
        i = 0
        for y in ys:
            for x in xs:
                name = f"channel_{i}"
                _y = y
                if ygap > 0:
                    _y += 0.5 * (y // ygap)

                fp.xs.append(x)
                fp.ys.append(_y)
                fp.rots.append(0)
                fp.cnames.append(name)
                fp.eqs.append(f"{name}")

                fp.cmaps.append("red_cmap")
                fp.templates.append("box")
                i += 1

        fp.num_dets = len(fp.xs)
        fp.chan_mask = np.arange(fp.num_dets)
        return fp

    @classmethod
    def from_tune_csv(cls, tune_csv, wafer_scale=50):
        det_map = np.genfromtxt(
            tune_csv, delimiter=',', skip_header=1, dtype=None
        )

        cmaps = {
            90: "red_cmap",
            150: "blue_cmap",
        }
        templates = {
            90: 'csv_template_c0_p0',
            150: 'csv_template_c1_p0',
        }
        fp = cls(ndets=len(det_map))
        eq = '/ + 1 s {} 2'
        map_inv = []  # Mapping from fp idx to channel number
        for i, det in enumerate(det_map):
            band, chan, freq, x, y, pol_angle = [
                det[idx] for idx in [1, 2, 12, 17, 18, 19]
            ]
            try:
                freq = int(freq)
            except:
                freq = 90
            abschan = band * 512 + chan
            map_inv.append(abschan)
            fp.xs[i] = x * wafer_scale
            fp.ys[i] = y * wafer_scale
            fp.rots[i] = np.deg2rad(pol_angle)
            fp.cnames[i] = f"chan_{abschan}"
            fp.eqs[i] = eq.format(fp.cnames[i])
            fp.cmaps[i] = cmaps[freq]
            fp.templates[i] = templates[freq]
        map_inv = np.array(map_inv)
        # Mapping form channel no. to fp-idx
        fp.chan_mask = np.full(np.max(map_inv)+1, -1)
        for idx, chan in enumerate(map_inv):
            fp.chan_mask[chan] = idx

        return fp

    @classmethod
    def from_wafer_file(cls, wafer_file, wafer_scale=50):
        import quaternionarray as qa
        import toml

        dets = toml.load(wafer_file)
        fp = cls(ndets=len(dets))
        band_idxs = {}
        bands_seen = 0

        xaxis = np.array([1., 0., 0.])
        zaxis = np.array([0., 0., 1.])
        cmaps = ["red_cmap", "blue_cmap"]

        def det_coords(det):
            quat =np.array(det['quat']).astype(np.float64)
            rdir = qa.rotate(quat, zaxis).flatten()
            ang = np.arctan2(rdir[1], rdir[0])
            orient = qa.rotate(quat, xaxis).flatten()
            polang = np.arctan2(orient[1], orient[0])
            mag = np.arccos(rdir[2]) * 180 / np.pi
            xpos = mag * np.cos(ang)
            ypos = mag * np.sin(ang)
            return (xpos, ypos), polang

        for key, det in dets.items():
            chan = det['channel']
            (x, y), polangle = det_coords(det)

            if det['band'] not in band_idxs:
                band_idxs[det['band']] = bands_seen
                bands_seen += 1
            color_idx = band_idxs[det['band']]

            fp.xs[chan] = x * wafer_scale
            fp.ys[chan] = y * wafer_scale
            fp.rots[chan] = polangle
            fp.cnames[chan] = key
            fp.eqs[chan] = f"/ + 1 s {key} 2"
            fp.cmaps[chan] = cmaps[color_idx]
            fp.templates[chan] = f"template_c{color_idx}_p0"

        return fp



class MagpieAgent:
    mask_register = 'AMCc.SmurfProcessor.ChannelMapper.Mask'

    def __init__(self, agent, args):
        self.agent = agent
        self._running = False

        self.target_rate = args.target_rate
        layout = args.layout.lower()
        if layout == 'grid':
            self.fp = FocalplaneConfig.grid(
                args.xdim, args.ydim, ygap=8
            )
        elif layout == 'wafer':
            if args.csv_file is not None:
                self.fp = FocalplaneConfig.from_tune_csv(
                    args.csv_file, wafer_scale=args.wafer_scale
                )
            else:
                self.fp = FocalplaneConfig.from_wafer_file(
                    args.wafer_file, wafer_scale=args.wafer_scale
                )

        self.sent_cfg = False
        self.num_dets = self.fp.num_dets
        self.mask = np.arange(self.num_dets)
        self.mask = np.arange(4960)

        self.reader = core.G3Reader(args.src)
        self.sender = core.G3NetworkSender(
            hostname='*', port=args.dest, max_queue_size=1000
        )

        self.out_queue = queue.Queue()
        self.delay = 0

        self.lowpass = FIRFilter.butter_lowpass(
            self.target_rate, self.target_rate * 2 + 1, order=4)
        self.send_config_flag = True
        self.scale = 1
        self.offsets = np.zeros(self.fp.num_dets)
        self.zero_flag = True

        self.demodulate = False
        #self.demod_filter = FIRFilter.butter_lowpass(1, 200., order=4)
        self.demod_freq = 4

    def set_scale(self, session, params=None):
        """
        Task to set the scaling factor by which timestreams should be
        multiplied by. This is currently necessary while we are still fine
        tuning the color scale, we may soon be able to remove it.

        Args:
            scale (float):
                scale factor to multiple det timestreams before sending to
                lyrebird
        """
        if params is None:
            params = {}
        self.scale = params['scale']
        return True, f"Set scale to {self.scale}"

    def zero_dets(self, session, params=None):
        """
        Task to zero out detector timestreams if they've drifted too far,
        messing up the color scale. Again, this might not be needed if we
        improve how the color mapping of detector data.
        """
        self.zero_flag = True
        return True, "Zeroing detectors"

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

    def set_demod(self, session, params=None):
        """
        Sets demodulation parameters. Detector demodulation is still in
        development and needs more testing.

        Args:
            state (bool, optional):
                Enables or disables the demod filters freq (float, optional):
                Sets the demodulation frequency
            lowpass_order: (int, optional):
                Sets the order of the demod filter
        """
        if params is None:
            params = {}
        if 'state' in params:
            self.demodulate = params['state']
        if 'freq' in params:
            self.demod_freq = params['freq']
        if ('lowpass_order' in params) or ('lowpass_cutoff'):
            order = params.get('lowpass_order', 4)
            cutoff = params.get('lowpass_cutoff', 1)
            self.demod_filter = FIRFilter.butter_lowpass(cutoff, 200., order=order)
        return True, f"set demod {params}"

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

        ds_factor = sample_rate // self.target_rate
        if np.isnan(ds_factor):  # There is only one element in the timestream
            ds_factor = 1
        ds_factor = max(int(ds_factor), 1)  # Prevents downsample factors < 1

        # Filter and process data
        sample_idxs = np.arange(0, nsamps, ds_factor, dtype=np.int32)
        num_frames = len(sample_idxs)

        data_out = np.zeros((num_frames, np.max(self.fp.chan_mask)+1))
        times_out = times_in[sample_idxs]

        chans = self.mask[np.arange(nchans)]

        if self.demodulate:
            template = np.sin(2*np.pi*self.demod_freq * times_in)
            data_in *= template
            self.demod_filter.lfilt(data_in)
        else:
            self.lowpass.lfilt(data_in)

        if self.zero_flag:
            self.offsets = np.mean(data_in, axis=1)
            self.zero_flag = False

        for i, c in enumerate(chans):
            if c >= len(self.fp.chan_mask):
                continue
            idx = self.fp.chan_mask[c]
            if idx >= 0:
                data_out[:, idx] = (data_in[i, sample_idxs]-self.offsets[i]) * self.scale

        out = []

        print("Queue size: ", self.out_queue.qsize())
        for i in range(num_frames):
            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            fr['data'] = core.G3VectorDouble(data_out[i, :])
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
    parser.add_argument('--wafer-file', '--wf', '-f', type=str,
                        help="Wafer file to pull detector info from")
    parser.add_argument('--wafer-scale', '--ws', type=float, default=50.,
                        help="scale of wafer coordinates")
    parser.add_argument('--csv-file', type=str, help="Tune csv file")
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
    agent.register_task('set_scale', magpie.set_scale)
    agent.register_task('zero', magpie.zero_dets)
    agent.register_task('set_demod', magpie.set_demod)

    runner.run(agent, auto_reconnect=True)
