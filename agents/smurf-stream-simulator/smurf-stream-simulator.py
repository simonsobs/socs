from ocs import ocs_agent, site_config
from spt3g import core
import time
import numpy as np


class StreamChannel:
    def __init__(self, mean, stdev):
        self.mean = mean
        self.stdev = stdev

    def read(self, t):
        return np.random.normal(self.mean, self.stdev)


class SmurfStreamSimulator:
    def __init__(self, agent, port=4536, num_chans=528):
        """

        OCS Agent to simulate data streaming without connection to a smurf.
        """
        self.agent = agent
        self.log = agent.log

        self.port = port

        self.writer = core.G3NetworkSender(hostname="*", port=self.port)

        self.is_streaming = False

        self.channels = [
            StreamChannel(0, 1) for i in range(num_chans)
        ]

    def start_stream(self, session, params=None):
        """
        Task to stream fake detector data as G3Frames

        Args:
            frame_rate (float, optional):
                Frequency [Hz] at which G3Frames are sent over the network.
                Defaults to 1 frame pers sec.
            sample_rate (float, optional):
                Sample rate [Hz] for each channel.
                Defaults to 10 Hz.
        """
        if params is None:
            params = {}

        frame_rate = params.get('frame_rate', 1.)
        sample_rate = params.get('sample_rate', 10.)

        f = core.G3Frame(core.G3FrameType.Observation)
        f['session_id'] = 0
        f['start_time'] = time.time()
        self.writer.Process(f)

        frame_num = 0
        self.is_streaming = True
        while self.is_streaming:

            frame_start = time.time()
            time.sleep(1. / frame_rate)
            frame_stop = time.time()
            times = np.arange(frame_start, frame_stop, 1./ sample_rate)

            f = core.G3Frame(core.G3FrameType.Scan)
            f['session_id'] = 0
            f['frame_num'] = frame_num
            f['data'] = core.G3TimestreamMap()

            for i, chan in enumerate(self.channels):
                ts = core.G3Timestream([chan.read(t) for t in times])
                ts.start = core.G3Time(frame_start * core.G3Units.sec)
                ts.stop = core.G3Time(frame_stop * core.G3Units.sec)
                f['data'][str(i)] = ts

            self.writer.Process(f)
            self.log.info("Writing frame...")
            frame_num += 1

        return True, "Finished streaming"

    def stop_stream(self, session, params=None):
        self.is_streaming = False
        return True, "Stopping stream"


if __name__ == '__main__':
    parser = site_config.add_arguments()
    args = parser.parse_args()
    site_config.reparse_args(args, 'SmurfStreamSimulator')

    agent, runner = ocs_agent.init_site_agent(args)
    sim = SmurfStreamSimulator(agent, port=int(args.port), num_chans=int(args.num_chans))

    # agent.register_task('set', ss.set_channel)
    agent.register_process('stream', sim.start_stream, sim.stop_stream)

    runner.run(agent, auto_reconnect=True)

