from scipy import signal

class FIRFilter:
    """
    Finite Impact Respone filter that can quickly filter n-dimensional data.
    This class internally keeps track of the filter delays so that long
    timestreams can be filtered in chunks without ringing and edge effects.
    """
    def __init__(self, b, a, nchans):
        self.b = b
        self.a = a
        self.z = np.zeros((nchans, len(b)-1))

    def lfilt(self, data, in_place=True):
        n = len(data)
        if in_place:
            data[:, :], self.z[:n] = signal.lfilter(
                self.b, self.a, data, axis=1, zi=self.z[:n])
        else:
            _data, self.z[:n] = signal.lfilter(
                self.b, self.a, data, axis=1, zi=self.z[:n])
            return _data

    @classmethod
    def butter_highpass(cls, cutoff, fs, order=5, nchans=1):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='high', analog=False)
        return cls(b, a, nchans)

    @classmethod
    def butter_lowpass(cls, cutoff, fs, order=5, nchans=1):
        nyq = 0.5 * fs
        normal_cutoff = cutoff / nyq
        b, a = signal.butter(order, normal_cutoff, btype='low', analog=False)
        return cls(b, a, nchans)

