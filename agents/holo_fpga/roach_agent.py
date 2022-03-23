import argparse
import os
import time

import numpy as np
import txaio
import yaml

ON_RTD = os.environ.get("READTHEDOCS") == "True"
if not ON_RTD:
    import casperfpga
    from holog_daq import fpga_daq3, poco3, synth3
    from ocs import ocs_agent, site_config
    from ocs.ocs_twisted import Pacemaker, TimeoutLock


class FPGAAgent:
    """
    Agent for connecting to the Synths for holography
    
    Args: 
    """

    def __init__(self, agent, config_file):

        self.fpga = None
        self.initialized = False
        # self.take_data = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        """
        if mode == 'acq':
            self.auto_acq = True
        else:
            self.auto_acq = False
        self.sampling_frequency = float(samp)

        ### register the position feeds

        ### Agent registers data feed, things published to feed go to grafana and .g3 files
        ### pick a good name for feeds, once it's registered it's kinda permanent
        
        """
        agg_params = {"frame_length": 10 * 60}  # [sec]
        self.agent.register_feed(
            "fpga", record=True, agg_params=agg_params, buffer_time=0
        )

        # Load dictionary of specific mirror paramters, since some parameters
        # like limits and translate vary over different FTSes This is loaded
        # from a yaml file, which is assumed to be in the $OCS_CONFIG_DIR
        # directory.
        if config_file == "None":
            raise Exception("No config file specified for the FTS mirror config")
        else:
            config_file_path = os.path.join(os.environ["OCS_CONFIG_DIR"], config_file)
            print(config_file_path)
            with open(config_file_path) as stream:
                self.holog_configs = yaml.safe_load(stream)
                if self.holog_configs is None:
                    raise Exception("No mirror configs in config file.")
                self.log.info(f"Loaded mirror configs from file {config_file_path}")
                self.baseline = self.holog_configs.pop("baseline", None)
                self.roach = self.holog_configs.pop("roach", None)

                # The other mirror configs (speed, timeout) are optional and
                # have defaults so we leave them as the dictionary.
                if self.roach is None or self.baseline is None:
                    raise Exception("IP address and channels must be included "
                                    "in the holography configuration keys.")

    def init_FPGA(self, session, params=None):

        if params is None:
            params = {}

        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=1, job="init") as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn(
                    "Could not start init because {} is already running".format(
                        self.lock.job
                    )
                )
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired initializing the FPGA")

            print("Programming FPGA with python2")
            err = os.system(
                "/opt/anaconda2/bin/python2 /home/chesmore/Desktop/holog_daq/scripts/upload_fpga_py2.py"
            )
            assert err == 0

            self.fpga = casperfpga.CasperFpga(self.roach)

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True

        return True, "FPGA connected."

    def take_data(self, session, params=None):

        with self.lock.acquire_timeout(timeout=3, job="take_data") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set position because lock held by {self.lock.job}"
                )
                return False, "Could not acquire lock"

            # Grab synthesizer settings here (which FPGA bins to integrate over)
            self.synth_settings = synth3.SynthOpt()

            self.synth_settings.IGNORE_PEAKS_BELOW = int(738)
            self.synth_settings.IGNORE_PEAKS_ABOVE = int(740)
            # Take data here
            arr_aa, arr_bb, arr_ab, arr_phase, arr_index = fpga_daq3.TakeAvgData(
                self.baseline, self.fpga, self.synth_settings
            )

            # Data dictionary is what we will send to the data feed:
            data = {"timestamp": time.time(), "block_name": "fpga", "data": {}}

            arr_AA = np.array(fpga_daq3.running_mean(arr_aa.tolist(), 1))
            arr_BB = np.array(fpga_daq3.running_mean(arr_bb.tolist(), 1))
            arr_AB = np.array(fpga_daq3.running_mean(arr_ab.tolist(), 1))
            arr_P = np.array(fpga_daq3.running_mean(arr_phase.tolist(), 1))

            n_channels = np.size(arr_AA)

            amp_AA = arr_AA[int(n_channels / 2)]
            amp_BB = arr_BB[int(n_channels / 2)]
            amp_AB = np.power(arr_AB[int(n_channels / 2)], 1)
            amp_P = np.remainder(arr_P[int(n_channels / 2)], 360.0)

            data["data"]["amp_AA"] = amp_AA
            data["data"]["amp_BB"] = amp_BB
            data["data"]["amp_AB"] = amp_AB
            data["data"]["amp_P"] = amp_P

            self.agent.publish_to_feed("fpga", data)
            session.data.update(data["data"])

            pass

        return True, "Data acquired."


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--config_file")

    return parser


if __name__ == "__main__":
    # For logging
    txaio.use_twisted()
    LOG = txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class="FPGAAgent", parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)

    fpga_agent = FPGAAgent(agent, args.config_file)

    agent.register_task("init_FPGA", fpga_agent.init_FPGA)
    agent.register_task("take_data", fpga_agent.take_data)

    runner.run(agent, auto_reconnect=True)
