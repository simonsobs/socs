import argparse
import os
import time

import txaio
import yaml
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock

ON_RTD = os.environ.get("READTHEDOCS") == "True"
if not ON_RTD:
    from holog_daq import synth3


class SynthAgent:
    """
    Agent for connecting to the Synths for holography.

    Args:
        config_file (str): ocs-site-configs/uchicago/field/holog_config.yaml
    """

    def __init__(self, agent, config_file):

        self.lo_id = None
        self.initialized = False
        self.take_data = False

        self.agent = agent
        self.log = agent.log
        self.lock = TimeoutLock()

        agg_params = {"frame_length": 10 * 60}  # [sec]
        self.agent.register_feed(
            "synth_lo", record=True, agg_params=agg_params, buffer_time=0
        )

        if config_file is None:
            raise Exception("No config file specified for the FTS mirror config")
        else:
            config_file_path = os.path.join(os.environ["OCS_CONFIG_DIR"], config_file)

            with open(config_file_path) as stream:
                self.holog_configs = yaml.safe_load(stream)
                if self.holog_configs is None:
                    raise Exception("No mirror configs in config file.")
                self.log.info(f"Loaded mirror configs from file {config_file_path}")
                self.N_MULT = self.holog_configs.pop("N_MULT", None)
                self.ghz_to_mhz = self.holog_configs.pop("ghz_to_mhz", None)

    def init_synth(self, session, params=None):
        """init_synth()

        **Task** - A task to initialize the synthesizers.

        Examples:
            Example for calling in a client::

                from ocs.ocs_client import OCSClient
                client = OCSClient("synth_lo")
                client.init_synth()

        Notes:
            This task is called to turn on the synthesizers.
        """

        self.log.debug("Trying to acquire lock")
        with self.lock.acquire_timeout(timeout=0, job="init") as acquired:
            # Locking mechanism stops code from proceeding if no lock acquired
            if not acquired:
                self.log.warn(
                    "Could not start init because {} is already running".format(
                        self.lock.job
                    )
                )
                return False, "Could not acquire lock."
            # Run the function you want to run
            self.log.debug("Lock Acquired Connecting to Stages")
            self.lo_id = synth3.get_LOs()

            synth3.set_RF_output(0, 1, self.lo_id)  # LO ID, On=1, USB connection ID
            synth3.set_RF_output(1, 1, self.lo_id)  # LO ID, On=1, USB connection ID

            # data = {"timestamp": time.time(), "block_name": "synth_lo", "data": {}}

            # data["data"]["F1_status"] = 1
            # data["data"]["F2_status"] = 1

            # self.agent.publish_to_feed("synth_lo", data)
            # session.data.update(data["data"])

        # This part is for the record and to allow future calls to proceed,
        # so does not require the lock
        self.initialized = True

        return True, "Synth Initialized."

    @ocs_agent.param("offset", type=float, default=0, check=lambda x: 0 <= x <= 1000)
    @ocs_agent.param("freq1", type=float, default=0, check=lambda x: 0 <= x <= 1000)
    def set_frequencies(self, session, params):
        """set_frequencies(freq1=0, offset=0)

        **Task** - A task to set the frequencies of the synthesizers.

        Parameters:
            freq1 (float): Frequency of holography measuremnt [GHz].
            offset (float): Frequency offset of holography measurement [MHz].

        Examples:
            Example for calling in a client::

                from ocs.ocs_client import OCSClient
                client = OCSClient("synth_lo")
                client.set_frequencies(freq1=210, offset=10)

        Notes:
            An example of the session data::

                >>> response.session['data']
                {"timestamp": 1601924482.722671,
                 "block_name": "synth_lo",
                 "data": {"F1": 11 ,
                          "F2": 11.1}}}
        """
        f1 = params.get("freq1", 0)
        f_offset = params.get("offset", 0)

        F_1 = int(f1 * self.ghz_to_mhz / self.N_MULT)  # Convert GHz -> MHz for synthesizers

        with self.lock.acquire_timeout(timeout=3, job="set_frqeuencies") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set position because lock held by {self.lock.job}"
                )
                return False, "Could not acquire lock"

            synth3.set_f(0, F_1, self.lo_id)
            synth3.set_f(1, F_1 + f_offset, self.lo_id)

            data = {"timestamp": time.time(), "block_name": "synth_lo", "data": {}}

            data["data"]["F1"] = F_1
            data["data"]["F2"] = F_1 + f_offset

            self.agent.publish_to_feed("synth_lo", data)
            session.data.update(data["data"])

        return True, "Frequencies Updated"

    # This function is not finished, need to figure out how to read out frequency from USB connection.
    # def read_frequencies(self, session, params=None):

    #     with self.lock.acquire_timeout(timeout=3, job="read_frqeuencies") as acquired:
    #         if not acquired:
    #             self.log.warn(
    #                 f"Could not set position because lock held by {self.lock.job}"
    #             )
    #             return False, "Could not acquire lock"

    #     return True, "Frequencies Updated"

    @ocs_agent.param("lo_id", type=int, default=0, choices=[0, 1])
    @ocs_agent.param("status", type=int, default=0, choices=[0, 1])
    def set_synth_status(self, session, params):
        """set_synth_status(lo_id=0, status=1)

        **Task** - A task to set the status of the synthesizers.

        Parameters:
            lo_id (int): Local Oscillator ID (either 0 or 1).
            status (int): Status of local oscillator (0 is off, 1 is on).

        Examples:
            Example for calling in a client::

                from ocs.ocs_client import OCSClient
                agent = OCSClient("synth_lo")
                agent.set_synth_status(lo_id=0, status=1)

        Notes:
            An example of the session data::

                >>> response.session['data']
                {"timestamp": 1601924482.722671,
                 "block_name": "synth_lo",
                 "data": {"F1_status": 1}}
        """
        lo_id = params.get("lo_id", 0)
        switch = params.get("switch", 0)

        with self.lock.acquire_timeout(timeout=3, job="turn_on_or_off_synth") as acquired:
            if not acquired:
                self.log.warn(
                    f"Could not set position because lock held by {self.lock.job}"
                )
                return False, "Could not acquire lock"

            synth3.set_RF_output(lo_id, switch, self.lo_id)

            data = {"timestamp": time.time(), "block_name": "synth_lo", "data": {}}

            data["data"]["F1_status"] = switch

            self.agent.publish_to_feed("synth_lo", data)
            session.data.update(data["data"])

        return True, "Frequencies Updated"


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


def main(args=None):
    # For logging
    txaio.use_twisted()
    txaio.make_logger()

    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = make_parser()

    # Interpret options in the context of site_config.
    args = site_config.parse_args(agent_class="SynthAgent",
                                  parser=parser,
                                  args=args)

    agent, runner = ocs_agent.init_site_agent(args)

    synth_agent = SynthAgent(agent, args.config_file)

    agent.register_task("init_synth", synth_agent.init_synth)
    agent.register_task("set_frequencies", synth_agent.set_frequencies)
    # agent.register_task("read_frequencies", synth_agent.read_frequencies)
    agent.register_task("set_synth_status", synth_agent.set_synth_status)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
