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
    def __init__(self, agent, args):
        self.streaming = False
        self.log = agent.log
        self.file_duration = args.file_duration
        self.basedir = args.base_dir
        if not os.path.exists(self.basedir):
            raise ValueError(f"Basedir {self.basedir} does not exist")

        self.smurfdir = os.path.join(self.basedir, 'smurf')
        self.timestreamdir = os.path.join(self.basedir, 'timestreams')

    def _write_smurf_file(self, name, action, action_time=None):
        t = int(time.time())
        if action_time is None:
            action_time = t
        timecode = f"{action_time}"[:5]
        subdir = os.path.join(
            self.smurfdir, timecode, f'{action_time}_{action}'
        )
        os.makedirs(subdir, exist_ok=True)
        filepath = os.path.join(subdir, f'{t}_{name}')
        self.log.info(f"Writing smurf file: {filepath}")
        with open(filepath, 'w') as f:
            f.write(f'start: {time.time()}\n')


    @ocs_agent.param('nchans', type=int, default=4096)
    @ocs_agent.param('sample_rate', type=float, default=200.)
    def stream(self, session, params=None):
        self.streaming = True

        # Writes IV file
        self._write_smurf_file("IV.npy", 'take_IV')

        session_id = int(time.time())
        seq = 0
        timecode = f"{session_id}"[:5]
        subdir = os.path.join(self.timestreamdir, timecode)
        os.makedirs(subdir, exist_ok=True)
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
        self.streaming= False


def make_parser(parser=None):
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group('Agent Options')
    pgroup.add_argument('--base-dir')
    pgroup.add_argument("--stream-on-start", action='store_true')
    pgroup.add_argument('--file-duration', default=10*60, type=int)

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

