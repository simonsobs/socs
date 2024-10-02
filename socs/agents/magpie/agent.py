import argparse
import ast
import os
import queue
import time

import numpy as np
import so3g  # noqa: F401
import txaio
import yaml
from ocs import ocs_agent, site_config
from scipy import signal
from spt3g import core

MAX_CHANS = 4096
CHANS_PER_BAND = 512
pA_per_rad = 9e6 / (2 * np.pi)


# Map from primary key-names to their index in the SuperTimestream
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
            data[i] = d[f'r{i:0>4}'] * (2 * np.pi) / 2**16

    else:  # G3SuperTimestream probably
        data = d.data * (2 * np.pi) / 2**16

    return times, data


def sleep_while_running(duration, session, interval=1):
    """
    Sleeps for a certain duration as long as a session object's status is
    'starting' or 'running'. If the session is changed to 'stopping',
    this will quickly return False. If the sleep is completed without
    interruption this will return True.

    Args
    ----
    duration : float
        Amount of time (sec) to sleep for.
    session : OpSessions
        Session whose status should be monitored
    interval : float, optional
        Polling interval (sec) to check the session status. Defaults to 1 sec.
    """
    end_time = time.time() + duration
    while session.status in ['starting', 'running']:
        now = time.time()
        if now >= end_time:
            return True
        time.sleep(min(interval, end_time - now))
    return False


class FIRFilter:
    """
    Class for Finite Input Response filter. Filter state is preserved
    between `lfilt` calls so you can filter frame-based data.

    From scipy docs, the output of the filter is determined by:

        a[0]*y[n] = b[0]*x[n] + b[1]*x[n-1] + ... + b[M]*x[n-M]
                              - a[1]*y[n-1] - ... - a[N]*y[n-N]
    """

    def __init__(self, b, a, nchans=None):
        if nchans is None:
            nchans = MAX_CHANS
        self.b = b
        self.a = a
        self.z = np.zeros((nchans, len(b) - 1))

    def lfilt(self, data, in_place=True):
        """Filters data in place"""
        n = len(data)
        if in_place:
            data[:, :], self.z[:n] = signal.lfilter(
                self.b, self.a, data, axis=1, zi=self.z[:n]
            )
        else:
            d, self.z[:n] = signal.lfilter(
                self.b, self.a, data, axis=1, zi=self.z[:n]
            )
            return d

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

    @classmethod
    def moving_avg(cls, width):
        """
        Creates a moving avg filter

        Args
        -----
        width : int
            number of samples to average together
        """
        b = 1. / width * np.ones(width, dtype=float)
        a = np.zeros_like(b)
        a[0] = 1
        return cls(b, a)

    @classmethod
    def differ(cls, delay=1):
        """
        FIR filter to calculate a rolling diff of incoming data.

        Args
        ----
        delay : int
            Sets the diff spacing
        """
        b = np.zeros(1 + int(delay))
        a = np.zeros_like(b)
        b[0], b[-1] = 1, -1
        a[0] = 1
        return cls(b, a)


class Demodulator:
    """
    Helper class for demodulating a live timestream

    Args
    -----
    f : float
        Demodulation frequency
    bw : float
        Bandwidth. This will be the filter-cutoff of the applied lowpass filter
    fs : float
        Sample rate of incoming data
    """

    def __init__(self, f, bw=1, fs=200):
        self.f = f
        self.lp_sin = FIRFilter.butter_lowpass(bw, fs)
        self.lp_cos = FIRFilter.butter_lowpass(bw, fs)

    def apply(self, times, data):
        """
        Applies demodulation to data segment.

        Returns
        --------
        demod : np.ndarray
            Array of (unnormalized) demodulated data in the same shape as the
            input data
        """
        sin = np.sin(2 * np.pi * self.f * times)
        cos = np.cos(2 * np.pi * self.f * times)

        # We don't really care about normalization
        demod_sin = self.lp_sin.lfilt(data * sin[None, :], in_place=False)
        demod_cos = self.lp_cos.lfilt(data * cos[None, :], in_place=False)

        return np.sqrt(demod_sin**2 + demod_cos**2)


class WhiteNoiseCalculator:
    """
    Helper class for calculating white noise levels of incoming data

    Args
    -----
    fs : float
        Sample rate of incoming data
    navg : int
        Number of samples to average over in the RMS calc
    """

    def __init__(self, fs=200, navg=200):
        # Aiming for 20 Hz
        delay = fs // 20
        self.differ = FIRFilter.differ(delay=delay)
        self.averager = FIRFilter.moving_avg(navg)
        self.fsamp = fs

    def apply(self, data):
        """
        Returns rms / sqrt(fsamp), which estimates the white noise level
        """
        return np.sqrt(
            self.averager.lfilt(
                self.differ.lfilt(data, in_place=False)**2, in_place=False
            ) / self.fsamp
        )


class VisElem:
    """
    Container for config info for Lyrebird visual elements.

    Attributes
    --------------
    name : str
        Name of the channel
    x : float
        x-coord of the element
    y : float
        y-coord of the element
    rot : float
        Rotation angle of the element (rads)
    vals : List[str]
        List containing the names of the data values corresponding to this
        visual element. All vis-elems must have the same number of
        data-values. Data-values must be unique, such as
        ``<channel_name>/rms``
    eqs : List[str]
        List of equations to be displayed by the visual element. Equations
        are written in Polish Notation, and may contain a combination of
        numbers and data-values. Data-values can be global as defined in
        the lyrebird config file, or channel values as defined in the
        ``value_names`` argument. There must be the same number of eqs per
        visual element.

        Polish notation is a method of writing equations where operators
        precede the operands, making it easier to parse and evaluate. For
        example, the operation :math:`a + b` will be ``+ a b`` in polish
        notation, and :math:`(a + b) / 2` can be written as ``/ + a b 2``.
        See the magpie docs page for a full list of operators that are
        accepted by lyrebird.
    eq_labels : List[str]
        List of strings used to label equations in the lyrebird gui. This
        list must have the same size as the ``eqs`` array.
    cmaps : List[str]
        List of colormaps to use for each equation. This must be the same
        size as the ``eqs`` array.
    template : str
        Template used for this vis-elem. Templates are defined in the
        lyrebird cfg file.
    abs_smurf_chan : int
        Absolute smurf-channel corresponding to this visual element.
    eq_color_is_dynamic : List[bool]
        List of booleans that determine if each equation's color-scale is
        dynamic or fixed. This must be the same size as the ``eqs`` array.
    """

    def __init__(self, name, x, y, rot, template, abs_smurf_chan, cmap_idx=0):
        self.x = x
        self.y = y
        self.rot = rot
        self.template = template
        self.abs_smurf_chan = abs_smurf_chan
        self.name = name

        vals = [
            '{name}/raw', '{name}/demod', '{name}/wl', '{name}/flagged',
            '{name}/smurf_band', '{name}/smurf_chan'
        ]
        self.vals = [v.format(name=name) for v in vals]
        eq_templates = {
            'raw': '{name}/raw',
            'demod': '* {name}/demod rms_scale',
            'wl': '* {name}/wl wl_scale',
            'flagged': '{name}/flagged',
            'smurf_band': f'{self.abs_smurf_chan // CHANS_PER_BAND}',
            'smurf_chan': f'{self.abs_smurf_chan % 512}',
        }

        self.eqs = [
            eq.format(name=name) for eq in eq_templates.values()
        ]
        self.eq_labels = [k for k in eq_templates.keys()]
        self.color_is_dynamic = [False for _ in self.eqs]
        self.color_is_dynamic[0] = True

        self.cmaps = [
            ['red_cmap' for _ in eq_templates],
            ['blue_cmap' for _ in eq_templates]
        ][cmap_idx]


class FocalplaneConfig:
    def __init__(self):
        """
        Object to configure the focal-plane layout.

        Attributes
        -------------
        chan_mask : np.ndarray
            Map from absolute_smurf_chan --> Visual Element index
        channels : list
            List of visual elements
        """
        self.channels = []
        self.chan_mask = np.full(MAX_CHANS, -1)

    def config_frame(self):
        """
        Generates a config frame for lyrebird
        """
        xs = []
        ys = []
        rots = []
        cnames = []
        templates = []
        value_names = []
        eqs = []
        eq_labels = []
        eq_color_is_dynamic = []
        cmaps = []

        for c in self.channels:
            xs.append(c.x)
            ys.append(c.y)
            rots.append(c.rot)
            cnames.append(c.name)
            templates.append(c.template)
            value_names.extend(c.vals)
            eqs.extend(c.eqs)
            eq_labels.extend(c.eq_labels)
            eq_color_is_dynamic.extend(c.color_is_dynamic)
            cmaps.extend(c.cmaps)

        frame = core.G3Frame(core.G3FrameType.Wiring)
        frame['x'] = core.G3VectorDouble(xs)
        frame['y'] = core.G3VectorDouble(ys)
        frame['cname'] = core.G3VectorString(cnames)
        frame['rotation'] = core.G3VectorDouble(rots)
        frame['templates'] = core.G3VectorString(templates)
        frame['values'] = core.G3VectorString(value_names)
        frame['color_is_dynamic'] = core.G3VectorBool(eq_color_is_dynamic)
        frame['equations'] = core.G3VectorString(eqs)
        frame['eq_labels'] = core.G3VectorString(eq_labels)
        frame['cmaps'] = core.G3VectorString(cmaps)
        return frame

    def add_vis_elem(self, *args, **kwargs):
        """
        Adds a visual element to the focal-plane and updates the channel mask
        """
        c = VisElem(*args, **kwargs)
        self.channels.append(c)
        self.chan_mask[c.abs_smurf_chan] = len(self.channels) - 1

    @classmethod
    def grid(cls, stream_id, xdim, ydim, ygap=0, offset=(0., 0.)):
        """
        Creates a FocalplaneConfig object for a grid of channels.

        Args
        ----
        stream_id : str
            Stream-id for the magpie agent. This will be prepended to all
            lyrebird data-val names.
        xdim : int
            Number of channels in the x-dim of the grid
        ydim : int
            Number of channels in the y-dim of the grid
        ygap : int
            A small gap will be added every ``ygap`` rows, to better organize
            channels.
        offset : Tuple(float, float)
            Global offset of the grid with respect to the lyrebird
            coordinate-system
        """
        fp = cls()
        xs, ys = np.arange(xdim), np.arange(ydim)
        xs = xs + offset[0]
        ys = ys + offset[1]

        # Adds gaps every ygap rows
        if ygap > 0:
            ys = ys + .5 * (ys // ygap)

        template = 'box'
        for i in range(xdim * ydim):
            x, y = xs[i % xdim], ys[i // xdim]
            name = f"{stream_id}/channel_{i}"
            fp.add_vis_elem(name, x, y, 0, template, i)

        return fp

    @classmethod
    def from_csv(cls, stream_id, detmap_file, wafer_scale=1., offset=(0, 0), rotation=0.):
        """
        Creates a FocalplaneConfig object from a detmap csv file.

        Args
        -----
        stream_id : str
            Stream-id for the magpie agent. This will be prepended to all
            lyrebird data-val names.
        detmap_file : str
            Path to detmap csv file.
        wafer_scale : int
            Scalar to multiply against det x and y positions when translating
            to lyrebird positions. Defaults to 1, meaning that the lyrebird
            coordinate system will be the same as the det-map coordinate system,
            so x and y will be in um.
        offset : Tuple(float, float)
            Global offset of the grid with respect to the lyrebird
            coordinate-system. If wafer_scale is 1, this should be in um.
        """
        import pandas as pd
        fp = cls()
        df = pd.read_csv(detmap_file)

        templates = ["template_c0_p0", "template_c1_p0", ]

        color_idxs = {}
        ncolors = 0
        for i, row in df.iterrows():
            rot = 0
            try:
                bandpass = int(row['bandpass'])
                if bandpass in color_idxs:
                    cidx = color_idxs[bandpass]
                else:
                    color_idxs[bandpass] = ncolors
                    ncolors += 1
                    cidx = color_idxs[bandpass]

                template = templates[cidx]
                if row['pol'].strip() == 'B':
                    rot = np.pi / 2
            except ValueError:
                # Just skip detectors with unknown bandpass
                continue

            x0, y0 = row['det_x'] * wafer_scale, row['det_y'] * wafer_scale
            x = x0 * np.cos(rotation) - y0 * np.sin(rotation) + offset[0]
            y = x0 * np.sin(rotation) + y0 * np.cos(rotation) + offset[1]

            band, chan = row['smurf_band'], row['smurf_channel']
            if chan == -1:
                continue
            abs_smurf_chan = band * CHANS_PER_BAND + chan

            name = f"{stream_id}/det_{i}"
            fp.add_vis_elem(name, x, y, rot, template, abs_smurf_chan, cmap_idx=cidx)

        return fp


class MagpieAgent:
    """
    Agent for processing streamed G3Frames, and sending data to lyrebird.

    Attributes
    -----------
    target_rate : float
        This is the target sample rate of data to be sent to lyrebird.
        Incoming data will be downsampled to this rate before being sent out.
    ds_offset : int
        Offset for downsample to avoid hiccups at frame boundaries
    fp : FocalplaneConfig
        This is the FocalplaneConfig object that contains info about what
        channels are present in the focal-plane representation, and their
        positions.
    mask : np.ndarray
        This is a channel mask that maps readout channel to
        absolute-smurf-chan. Before a status frame containing the ChannelMask
        is seen in the G3Stream, this defaults to being an identity mapping
        which just sends the readout channel no. to itself. Once a status
        frame with the channel mask is seen, this will be updated
    out_queue : Queue
        This is a queue containing outgoing G3Frames to be sent to lyrebird.
    delay : float
        The outgoing stream will attempt to enforce this delay between the
        relative timestamps in the G3Frames and the real time to ensure a
        smooth flow of data. This must be greater than the frame-aggregation
        time of the SmurfStreamer or else lyrebird will update data in spurts.
    avg1, avg2 : RollingAvg
        Two Rolling Averagers which are used to calculate the rolling RMS data.
    monitored_channels : list
        List of monitored channels whose data should be sent to grafana.
        This list will contain entries which look like
        ``(readout_chan_number, field_name)``.
    monitored_chan_sample_rate : float
        Sample rate (Hz) to target when downsampling monitored channel data for
        grafana.
    demod : Demodulator
        Demodulator used to calculate demod signal for incoming timestreams
    self.demod_freq : float
        Demodulation frequency
    self.demod_bandwidth : float
        Filter cutoff for demodulation lowpass
    wlcalc : WhiteNoiseCalculator
        WhiteNoiseCalculator used to calculate white noise levels for incoming
        timestreams
    """
    mask_register = 'AMCc.SmurfProcessor.ChannelMapper.Mask'

    def __init__(self, agent, args):
        self.agent: ocs_agent.OCSAgent = agent
        self.log = self.agent.log
        self._running = False

        self.target_rate = args.target_rate
        self.ds_offset = 0
        layout = args.layout.lower()
        if layout == 'grid':
            self.fp = FocalplaneConfig.grid(
                args.stream_id, args.xdim, args.ydim, ygap=8, offset=args.offset
            )
        elif layout == 'wafer':
            if args.det_map is not None:
                self.fp = FocalplaneConfig.from_csv(
                    args.stream_id, args.det_map, wafer_scale=args.wafer_scale,
                    offset=args.offset, rotation=args.rotation
                )
            else:
                raise ValueError("CSV file must be set using the det-map arg if "
                                 "using wafer layout")

        self.mask = np.arange(MAX_CHANS)
        self.out_queue = queue.Queue(1000)
        self.delay = args.delay

        self.demod = None
        self.demod_freq = args.demod_freq
        self.demod_bandwidth = args.demod_bandwidth

        self.wncalc = None

        self.monitored_channels = []
        self.monitored_chan_sample_rate = 10
        self.agent.register_feed(
            'detector_tods', record=True,
            agg_params={'exclude_aggregator': True}
        )
        self.agent.register_feed('white_noise', record=True,)

    @ocs_agent.param('target_rate', type=float)
    def set_target_rate(self, session, params):
        """set_target_rate(target_rate)

        Sets the target downsampled sample-rate of the data sent to lyrebird

        Args:
            target_rate : float
                Target sample rate for lyrebird (Hz)
        """
        self.target_rate = params['target_rate']
        return True, f'Set target rate to {self.target_rate}'

    @ocs_agent.param('delay', type=float)
    def set_delay(self, session, params):
        """set_delay(delay)

        Sets the target downsampled sample-rate of the data sent to lyrebird

        Args:
            target_rate : float
                Target sample rate for lyrebird (Hz)
        """
        self.delay = params['delay']
        return True, f'Set delay param to {self.delay}'

    @ocs_agent.param('chan_info', type=list, check=lambda x: len(x) <= 6)
    @ocs_agent.param('sample_rate', type=float, default=10,
                     check=lambda x: 0 < x <= 20)
    def set_monitored_channels(self, session, params):
        """set_monitored_channels(chan_info, sample_rate=10)

        **Task** - Sets channels which will be monitored and have their
        downsampled data sent to grafana.

        Field names can be manually specified in the chan_info list because it
        may be helpful to set a consistent name for specific channels, such as
        "in_transition", instead of using the autogenerated channel name, which
        can change between tunes. Any additional field names used will remain
        in the influx database, so be wary of programatically adding many of
        them.

        Args
        ------
        chan_info : list
            List of channel info corresponding to channels to monitor.
            Entries of this list can be:

              - ints: This will be interpreted as the readout-channel to
                monitor. The field-name will be set to "r<chan_no>".
              - tuples of length 2: Here the first element will be the readout
                chan to monitor, and the second value will be the field name to
                use for that channel.

            This list can be no more than 6 elements to limit how much detector
            data is saved to the HK format.

        sample_rate : float
            Target sample rate (Hz) to downsample detector data to. This must
            be less than 20 Hz to limit how much detector data is saved to hk.

        """
        monitored_chans = []
        for ch_info in params['chan_info']:
            if isinstance(ch_info, int):
                field_name = f"r{ch_info:0>4}"
                monitored_chans.append((ch_info, field_name))
            elif isinstance(ch_info, (tuple, list)):
                monitored_chans.append(ch_info)
            else:
                raise ValueError(
                    f"ch_info (type {type(ch_info)}) must be of type int or "
                    "tuple"
                )

        self.monitored_channels = monitored_chans
        self.monitored_chan_sample_rate = params['sample_rate']
        return True, "Set monitored channels"

    def _process_status(self, frame):
        """
        Processes a status frame. This will set or update the channel
        mask whenever the smurf metadata is updated.
        """
        if 'session_id' not in frame:
            return
        if self.mask_register in frame['status']:
            status = yaml.safe_load(frame['status'])
            self.mask = np.array(
                ast.literal_eval(status[self.mask_register])
            )

    def _process_monitored_chans(self, times, data):
        """
        Downsamples data for monitored channels and publishes tods to a grafana
        feed.
        """
        if not self.monitored_channels:
            return

        target_rate = self.monitored_chan_sample_rate
        if len(times) <= 1:
            ds_factor = 1
        else:
            input_rate = 1. / np.median(np.diff(times))
            ds_factor = max(int(input_rate // target_rate), 1)

        sl = slice(None, None, ds_factor)

        times_out = times[sl]
        for rc, field_name in self.monitored_channels:
            if rc >= len(data):
                self.log.warn(
                    f"Readout channel {rc} is larger than the number of"
                    f"streamed channels ({len(data)})! Data won't be published"
                    "to grafana."
                )
                continue
            _data = {
                'timestamps': times_out.tolist(),
                'block_name': field_name,
                'data': {
                    field_name: data[rc, sl].tolist()
                }
            }
            self.agent.publish_to_feed('detector_tods', _data)

    def _publish_wls(self, wls):
        """
        Publishes white-noise quantiles to ocs feed
        """
        quantiles = [15, 25, 50, 75, 85]
        labels = [f'white_noise_q{q}' for q in quantiles]
        data = {
            'timestamp': time.time(),
            'block_name': 'white_noise',
            'data': {
                k: np.quantile(wls, q / 100)
                for k, q in zip(labels, quantiles)
            }
        }
        self.agent.publish_to_feed('white_noise', data)

    def _process_data(self, frame, source_offset=0):
        """
        Processes a Scan frame. If lyrebird is enabled, this will return a seq
        of G3Frames that are formatted for lyrebird to ingest.
        """
        if 'session_id' not in frame:
            return []

        # Calculate downsample factor
        times_in, data_in = load_frame_data(frame)
        times_in = times_in - source_offset
        sample_rate = 1. / np.median(np.diff(times_in))
        nsamps = len(times_in)
        nchans = len(data_in)

        self._process_monitored_chans(times_in, data_in)

        if self.demod is None:
            self.demod = Demodulator(self.demod_freq, self.demod_bandwidth,
                                     fs=sample_rate)
        if self.wncalc is None:
            self.wncalc = WhiteNoiseCalculator(
                fs=sample_rate, navg=int(sample_rate)
            )

        demod = self.demod.apply(times_in, data_in)
        # white noise in units of pA/rt(Hz)
        wl = self.wncalc.apply(data_in * pA_per_rad)
        self._publish_wls(np.median(wl, axis=1))

        ds_factor = sample_rate // self.target_rate
        if np.isnan(ds_factor):  # There is only one element in the timestream
            ds_factor = 1
        ds_factor = max(int(ds_factor), 1)  # Prevents downsample factors < 1

        # Arrange output data structure
        sample_idxs = np.arange(self.ds_offset, nsamps, ds_factor, dtype=np.int32)
        self.ds_offset = ds_factor - (nsamps - self.ds_offset) % ds_factor
        num_frames = len(sample_idxs)

        times_out = times_in[sample_idxs]
        abs_chans = self.mask[np.arange(nchans)]

        nelems = len(self.fp.channels)
        raw_out = np.zeros((num_frames, nelems))
        demod_out = np.zeros((num_frames, nelems))
        wl_out = np.zeros((num_frames, nelems))

        for i, c in enumerate(abs_chans):
            if c >= len(self.fp.chan_mask):
                continue
            idx = self.fp.chan_mask[c]
            if idx >= 0:
                raw_out[:, idx] = data_in[i, sample_idxs]
                demod_out[:, idx] = demod[i, sample_idxs]
                wl_out[:, idx] = wl[i, sample_idxs]

        out = []
        for i in range(num_frames):
            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['idx'] = 0
            fr['data'] = core.G3VectorDouble(raw_out[i])
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            out.append(fr)

            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['idx'] = 1
            fr['data'] = core.G3VectorDouble(demod_out[i])
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            out.append(fr)

            fr = core.G3Frame(core.G3FrameType.Scan)
            fr['idx'] = 2
            fr['data'] = core.G3VectorDouble(wl_out[i])
            fr['timestamp'] = core.G3Time(times_out[i] * core.G3Units.s)
            out.append(fr)

        return out

    def read(self, session, params=None):
        """read(src='tcp://localhost:4532')

        **Process** - Process for reading in G3Frames from a source or list of
        sources. If this source is an address that begins with ``tcp://``, the
        agent will attempt to connect to a G3NetworkSender at the specified
        location. The ``src`` param can also be a filepath or list of filepaths
        pointing to G3Files to be streamed. If a list of filenames is passed,
        once the first file is finished streaming, subsequent files will be
        streamed.
        """

        self._running = True

        src_idx = 0
        if isinstance(params['src'], str):
            sources = [params['src']]
        else:
            sources = params['src']

        reader = None
        source = None
        source_offset = 0
        while self._running:

            if reader is None:
                try:
                    source = sources[src_idx]
                    source_is_file = not source.startswith('tcp://')
                    reader = core.G3Reader(source, timeout=5)
                except RuntimeError as e:
                    if source_is_file:
                        # Raise error if file cannot be found
                        raise e
                    else:
                        # If not a file, log error and try again
                        self.log.error("G3Reader could not connect! Retrying in 10 sec.")
                        time.sleep(10)
                        continue

            frames = reader.Process(None)
            if not frames:
                # If source is a file, start over with next file or break if
                # finished all sources. If socket, just reset reader and try to
                # reconnect
                if source_is_file:
                    src_idx += 1
                    if src_idx >= len(sources):
                        self.log.info("Finished reading all sources")
                        break
                reader = None
                continue

            frame = frames[0]

            # If this source is a file, this will shift the timestamps so that
            # data lines up with the current timestamp instead of using the
            # timestamps in the file
            if source_is_file and (not source_offset):
                source_offset = frame['time'].time / core.G3Units.s \
                    - time.time()
            elif not source_is_file:
                source_offset = 0

            if frame.type == core.G3FrameType.Wiring:
                self._process_status(frame)
                continue
            elif frame.type == core.G3FrameType.Scan:
                out = self._process_data(frame, source_offset=source_offset)
            else:
                continue

            for f in out:
                # This will block until there's a free spot in the queue.
                # This is useful if the src is a file and reader.Process does
                # not block
                self.out_queue.put(f)
        return True, "Stopped read process"

    def _stop_read(self, session, params=None):
        self._running = False
        return True, "Stopping read process"

    def stream_fake_data(self, session, params=None):
        """stream_fake_data()

        **Process** - Process for streaming fake data. This will queue up
        G3Frames full of fake data to be sent to lyrebird.
        """
        self._run_fake_stream = True
        ndets = len(self.fp.channels)
        chans = np.arange(ndets)
        frame_start = time.time()
        while self._run_fake_stream:
            time.sleep(2)
            frame_stop = time.time()
            ts = np.arange(frame_start, frame_stop, 1. / self.target_rate)
            frame_start = frame_stop
            nframes = len(ts)

            data_out = np.random.normal(0, 1, (nframes, ndets))
            data_out += np.sin(2 * np.pi * ts[:, None] + .2 * chans[None, :])

            for t, d in zip(ts, data_out):
                fr = core.G3Frame(core.G3FrameType.Scan)
                fr['idx'] = 0
                fr['data'] = core.G3VectorDouble(d)
                fr['timestamp'] = core.G3Time(t * core.G3Units.s)
                self.out_queue.put(fr)

                fr = core.G3Frame(core.G3FrameType.Scan)
                fr['idx'] = 1
                fr['data'] = core.G3VectorDouble(np.sin(d))
                fr['timestamp'] = core.G3Time(t * core.G3Units.s)
                self.out_queue.put(fr)

        return True, "Stopped fake stream process"

    def _stop_stream_fake_data(self, session, params=None):
        self._run_fake_stream = False
        return True, "Stopping fake stream process"

    @ocs_agent.param('dest', type=int)
    def send(self, session, params=None):
        """send(dest)

        **Process** - Process for sending outgoing G3Frames. This will query
        the out_queue for frames to be sent to lyrebird. This will try to
        regulate how fast it sends frames such that the delay between when the
        frames are sent, and the timestamp of the frames are fixed.

        """
        self._send_running = True

        first_frame_time = None
        stream_start_time = None

        sender = core.G3NetworkSender(
            hostname='*', port=params['dest'], max_queue_size=1000
        )

        sender.Process(self.fp.config_frame())
        while session.status in ['starting', 'running']:
            f = self.out_queue.get(block=True)
            t = f['timestamp'].time / core.G3Units.s
            now = time.time()
            if first_frame_time is None:
                first_frame_time = t
                stream_start_time = now

            this_frame_time = stream_start_time + (t - first_frame_time) + self.delay
            sleep_while_running(this_frame_time - now, session)
            sender.Process(f)

        return True, "Stopped send process"

    def _send_stop(self, session, params=None):
        self._send_running = False
        return True, "Stopping send process"


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--src', nargs='+', default='tcp://localhost:4532',
                        help="Address of incoming G3Frames.")
    pgroup.add_argument('--dest', type=int, default=8675,
                        help="Port to serve lyrebird frames")
    pgroup.add_argument('--stream-id', type=str, default='none',
                        help="Stream-id to use to distinguish magpie streams."
                             "This will be prepended to data-val names in lyrebird.")
    pgroup.add_argument('--target-rate', '-t', type=float, default=20,
                        help="Target sample rate for data being sent to Lyrebird. "
                             "Detector data will be downsampled to this rate.")
    pgroup.add_argument(
        '--delay', type=float, default=5,
        help="Delay (sec) between the timestamp of a G3Frame relative to the "
             "initial frame, and when the frame should be sent to lyrebird. "
             "This must be larger than the frame-aggregation time for smooth "
             "update times in lyrebird."
    )
    pgroup.add_argument('--layout', '-l', default='grid', choices=['grid', 'wafer'],
                        help="Focal plane layout style")
    pgroup.add_argument('--xdim', type=int, default=64,
                        help="Number of pixels in x-dimension for grid layout")
    pgroup.add_argument('--ydim', type=int, default=64,
                        help="Number of pixels in y-dimension for grid layout")
    pgroup.add_argument('--wafer-scale', '--ws', type=float, default=50.,
                        help="scale of wafer coordinates")
    pgroup.add_argument('--det-map', type=str, help="Path to det-map csv file")
    pgroup.add_argument('--fake-data', action='store_true',
                        help="If set, will stream fake data instead of listening to "
                             "a G3stream.")
    pgroup.add_argument('--offset', nargs=2, default=[0, 0], type=float,
                        help="Offset of detector coordinates with respect to "
                             "lyrebird coordinate system")
    pgroup.add_argument('--rotation', default=0., type=float,
                        help="Rotation of wafer about its center (rad)")
    pgroup.add_argument('--monitored-channels', nargs='+', type=int, default=[],
                        help="Readout channels to start monitoring on startup")
    pgroup.add_argument('--monitored-channel-rate', type=float, default=10,
                        help="Target sample rate for monitored channels")
    pgroup.add_argument('--demod-freq', type=float, default=8,
                        help="Demodulation frequency")
    pgroup.add_argument('--demod-bandwidth', type=float, default=0.5,
                        help="Demodulation bandwidth")
    return parser


def main(args=None):
    txaio.use_twisted()
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))
    parser = make_parser()
    args = site_config.parse_args(agent_class='MagpieAgent',
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)
    magpie = MagpieAgent(agent, args)

    if args.fake_data:
        read_startup = False
    else:
        read_startup = {'src': args.src}

    agent.register_process('read', magpie.read, magpie._stop_read,
                           startup=read_startup)
    agent.register_process('stream_fake_data', magpie.stream_fake_data,
                           magpie._stop_stream_fake_data, startup=args.fake_data)
    agent.register_process('send', magpie.send, magpie._send_stop,
                           startup={'dest': args.dest})
    agent.register_task('set_target_rate', magpie.set_target_rate)
    agent.register_task('set_delay', magpie.set_delay)
    agent.register_task(
        'set_monitored_channels', magpie.set_monitored_channels,
        startup={'chan_info': args.monitored_channels,
                 'sample_rate': args.monitored_channel_rate}
    )

    runner.run(agent, auto_reconnect=True)


if __name__ == '__main__':
    main()
