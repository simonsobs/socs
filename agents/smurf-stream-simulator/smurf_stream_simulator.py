import os
import time
import argparse
import numpy as np

ON_RTD = os.environ.get('READTHEDOCS') == 'True'
if not ON_RTD:
    from ocs import ocs_agent, site_config
    from spt3g import core


class StreamChannel:
    """Simulated SMuRF channel for stream testing.

    Uses np.random.normal to generate random Gaussian data.

    Parameters
    ----------
    mean : float
        Mean value of Gaussian to simulate data with
    stdev : float
        Standard deviation of Gaussian to simulate data

    """
    def __init__(self, mean, stdev):
        self.mean = mean
        self.stdev = stdev

    def read(self):
        """Read a value from the channel.

        Returns
        -------
        float
            Random, normally distributed, value

        """
        return np.random.normal(self.mean, self.stdev)


class SmurfStreamSimulator:
    """OCS Agent to simulate data streaming without connection to a SMuRF.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    port : int
        Port to send data over
    num_chans : int
        Number of channels to simulate

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    log : txaio.tx.Logger
        txaio logger ojbect, created by the OCSAgent
    target_host : str
        Target remote host address
    port : int
        Port to send data over
    writer : spt3g.core.G3NetworkSender
        G3NetworkSender object for sending the data
    is_streaming : bool
        flag to track if we're currently streaming, used in stop task to stop
        the streaming process
    channels : list
        List of simulated channels to stream

    """
    def __init__(self, agent, target_host="*", port=4536, num_chans=528):
        self.agent = agent
        self.log = agent.log

        self.port = port

        self.writer = core.G3NetworkSender(hostname=target_host,
                                           port=self.port)

        self.is_streaming = False

        self.channels = [
            StreamChannel(0, 1) for i in range(num_chans)
        ]

    def start_stream(self, session, params=None):
        """start_stream(params=None)

        Process to stream fake detector data as G3Frames.

        Parameters
        ----------
        frame_rate : float, optional
            Frequency [Hz] at which G3Frames are sent over the network.
            Defaults to 1 frame pers sec.
        sample_rate : float, optional
            Sample rate [Hz] for each channel. Defaults to 10 Hz.

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
            times = np.arange(frame_start, frame_stop, 1. / sample_rate)

            f = core.G3Frame(core.G3FrameType.Scan)
            f['session_id'] = 0
            f['frame_num'] = frame_num
            f['data'] = core.G3TimestreamMap()

            for i, chan in enumerate(self.channels):
                ts = core.G3Timestream([chan.read() for t in times])
                ts.start = core.G3Time(frame_start * core.G3Units.sec)
                ts.stop = core.G3Time(frame_stop * core.G3Units.sec)
                f['data'][str(i)] = ts

            self.writer.Process(f)
            self.log.info("Writing frame...")
            frame_num += 1

        return True, "Finished streaming"

    def stop_stream(self, session, params=None):
        """stop_stream(params=None)

        Stop method associated with start_stream process.

        """
        self.is_streaming = False
        return True, "Stopping stream"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--auto-start", default=False, type=bool,
                        help="Automatically start streaming at " +
                        "Agent startup.")
    pgroup.add_argument("--target-host", default="*",
                        help="Target remote host.")
    pgroup.add_argument("--port", default=50000,
                        help="Port to listen on.")
    pgroup.add_argument("--num-chans", default=528,
                        help="Number of detector channels to simulate.")

    return parser


if __name__ == '__main__':
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    args = parser.parse_args()
    site_config.reparse_args(args, 'SmurfStreamSimulator')

    agent, runner = ocs_agent.init_site_agent(args)
    sim = SmurfStreamSimulator(agent, target_host=args.target_host,
                               port=int(args.port),
                               num_chans=int(args.num_chans))

    agent.register_process('stream', sim.start_stream, sim.stop_stream,
                           startup=bool(args.auto_start))

    runner.run(agent, auto_reconnect=True)
