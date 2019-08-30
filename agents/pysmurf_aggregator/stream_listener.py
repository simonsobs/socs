import os
import time
import datetime

from ocs import ocs_agent, site_config
from spt3g import core


class G3StreamListener:
    def __init__(self, agent, address='localhost', port=4536):
        self.agent = agent
        self.log = self.agent.log
        self.address = address
        self.port = port
        self.is_streaming = False

    def start_stream(self, session, params=None):
        if params is None:
            params = {}

        time_per_file = params.get("time_per_file", 60*60)  # [sec]
        data_dir = params.get("data_dir", "data/")

        self.log.info("Writing data to {}".format(data_dir))
        self.log.info("New file every {} seconds".format(time_per_file))
        self.log.info("Listening to {}:{}".format(self.address, self.port))

        reader = core.G3Reader("tcp://{}:{}".format(self.address,
                                                    self.port))
        writer = None

        last_meta = None
        self.is_streaming = True

        while self.is_streaming:
            if writer is None:
                start_time = time.time()
                start_datetime = datetime.datetime \
                                         .fromtimestamp(start_time,
                                                        tz=datetime
                                                        .timezone.utc)

                sub_dir = os.path.join(data_dir,
                                       "{:.5}".format(str(start_time)))

                # Create new dir for current day
                if not os.path.exists(sub_dir):
                    os.makedirs(sub_dir)

                time_string = start_datetime.strftime("%Y-%m-%d-%H-%M-%S")
                filename = "{}.g3".format(time_string)
                filepath = os.path.join(sub_dir, filename)

                writer = core.G3Writer(filename=filepath)

                if last_meta is not None:
                    writer(last_meta)

            frames = reader.Process(None)
            for f in frames:
                if f.type == core.G3FrameType.Observation:
                    last_meta = f
                writer(f)

            if (time.time() - start_time) > time_per_file:
                writer(core.G3Frame(core.G3FrameType.EndProcessing))
                writer = None

        # Once we're done writing close out the file
        if writer is not None:
            writer(core.G3Frame(core.G3FrameType.EndProcessing))
            writer = None

        return True, "Finished Streaming"

    def stop_stream(self, session, params=None):
        self.is_streaming = False
        return True, "Stopping Streaming"


if __name__ == '__main__':
    parser = site_config.add_arguments()
    args = parser.parse_args()
    site_config.reparse_args(args, 'G3StreamListener')

    agent, runner = ocs_agent.init_site_agent(args)
    listener = G3StreamListener(agent,
                                address=args.address,
                                port=int(args.port))

    agent.register_process('stream',
                           listener.start_stream,
                           listener.stop_stream)

    runner.run(agent, auto_reconnect=True)
