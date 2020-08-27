import os
from os import environ

import time
import argparse
import txaio

from autobahn.twisted.util import sleep as dsleep
from twisted.internet.defer import inlineCallbacks

from socs.snmp import SNMPTwister

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config

# Mapping of integer OID values to meaningful strings from M1000 manual
REFCLOCKSTATE = {0: "refclock is not available",
                 1: "synchronized",
                 2: "not synchronized"}

NTPCURRENTSTATE = {0: "not available",
                   1: "not synchronized",
                   2: "synchronized"}

SYSPSSTATUS = {0: "notAvailable",
               1: "down",
               2: "up"}

ETHPORTLINKSTATE = {0: "notAvailable",
                    1: "up"}

PTPPORTSTATE = {0: "uninitialized",
                1: "initializing",
                2: "faulty",
                3: "disabled",
                4: "listening",
                5: "preMaster",
                6: "master",
                7: "passive",
                8: "uncalibrated",
                9: "slave"}


class MeinbergSNMP:
    """Meinberg SNMP communicator. Handles communication with and decoding of
    values from the Meinberg M1000.

    Parameters
    ----------
    address : str
        Address of the M1000.
    port : int
        SNMP port to issue GETs to, default to 161.

    Attributes
    ----------
    address : str
        Address of the M1000.
    port : int
        SNMP port to issue GETs to.
    snmp : socs.snmp.SNMPTwister
        snmp handler from SOCS
    decoder : dict
        dict to facilitate the decoding of integer OID values returned from
        queries to the M1000
    mib_timings : list
        list of dicts describing the SNMP OIDs to check, and at which
        intervals. Each dict contains the keys "oid", "interval", and
        "lastGet". The corresponding values are of types tuple, integer, and
        float, respectively. "lastGet" is initialized as None, since no SNMP
        GET commands have been issued.
    oid_cache : dict
        Cache of OID values and corresponding decoded values. Meant to pass to
        session.data.

    """
    def __init__(self, address, port=161):
        self.log = txaio.make_logger()
        self.address = address
        self.port = port
        self.snmp = SNMPTwister(address, port)

        # Decode OID States
        self.decoder = {'mbgLtNgRefclockState': REFCLOCKSTATE,
                        'mbgLtNgNtpCurrentState': NTPCURRENTSTATE,
                        'mbgLtNgSysPsStatus': SYSPSSTATUS,
                        'mbgLtNgEthPortLinkState': ETHPORTLINKSTATE,
                        'mbgLtNgPtpPortState': PTPPORTSTATE}

        # OIDs and how often to query them
        self.mib_timings = [{"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 1),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 2),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgEthPortLinkState', 1),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockLeapSecondDate', 1),
                             "interval": 60*60,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgNtpCurrentState', 0),
                             "interval": 64,
                             "lastGet": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgPtpPortState', 1),
                             "interval": 3,
                             "lastGet": None}]

        self.oid_cache = {}

        # Determine unique interval values
        self.interval_groups = list({x['interval'] for x in self.mib_timings})

    def dump_cache(self):
        """Return the current cache. Should be used to pass cached values to session.data.

        """
        return self.oid_cache

    def build_get_list(self, interval):
        """Create list of OIDs to GET based on last time we checked them.

        Intervals are defined in the mib_timings dictionary. If the interval
        time, or more, has passed since the last GET was issued, we add the OID to the
        get_list.

        Parameters
        ----------
        interval : int
            Interval to build the get list for. Since available fields cannot
            change dynamically within OCS we publish each interval group to its
            own block.

        Returns
        -------
        get_list : list
            List of OID tuples to be passed to an SNMPTwister object in a GET call.

        """
        get_list = []
        for mib in self.mib_timings:
            # Select only OIDs of the same interval
            if mib['interval'] != interval:
                continue

            if mib["lastGet"] is None:
                get_list.append(mib["oid"])
            elif time.time() - mib["lastGet"] > mib["interval"]:
                get_list.append(mib["oid"])

        return get_list

    @inlineCallbacks
    def get_intervals(self, session):
        # Loop through interval groups and issue get commands for each
        # interval group, publishing to a block with the interval in the
        # name.
        for interval in self.interval_groups:
            # SNMP GET response
            result = []

            # Create list of OIDs to GET based on last time we checked them
            get_list = self.build_get_list(interval)

            # empty if an interval of time hasn't passed since last GET
            if not get_list:
                continue

            # Issue SNMP GET command
            result = yield self.snmp.get(get_list)
            read_time = time.time()

            message = {
                'block_name': f'm1000_{interval}',
                'timestamp': read_time,
                'data': {}
            }

            for item in result:
                # OID from SNMP GET
                oid = item[0].prettyPrint()
                # Makes something like 'MBG-SNMP-LTNG-MIB::mbgLtNgRefclockState.1'
                # look like 'mbgLtNgRefclockState_1'
                field_name = oid.split("::")[1].replace('.', '_')

                # Grab OID value, mostly these are integers
                oid_value = item[1]._value

                # Decode string values
                if isinstance(oid_value, bytes):
                    oid_value = oid_value.decode("utf-8")

                if not isinstance(oid_value, (int, bytes)):
                    self.log.error("{oid} is of unknown and unhandled type " +
                                   "{oid_type}. This OID will not be recorded.",
                                   oid=oid, oid_type=type(oid_value))
                    continue

                self.log.debug("{o} {value}",
                               o=oid,
                               value=oid_value)
                message['data'][field_name] = oid_value

                # Update OID Cache for session.data
                self.oid_cache[field_name] = {"status": oid_value}
                oid_base_str = field_name.split('_')[0]
                if oid_base_str in self.decoder:
                    self.oid_cache[field_name]["description"] = self.decoder[oid_base_str][oid_value]
                    self.oid_cache[field_name]["lastGet"] = read_time

            # Update lastGet time
            for mib in self.mib_timings:
                if mib['oid'] in get_list:
                    mib['lastGet'] = read_time

            self.log.debug("{msg}", msg=message)
            session.app.publish_to_feed('m1000', message)
            session.data = self.dump_cache()


class MeinbergM1000Agent:
    """Monitor the Meinberg LANTIME M1000 timing system via SNMP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the M1000.
    port : int
        SNMP port to issue GETs to, default to 161.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the M1000. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent

    """
    def __init__(self, agent, address, port=161):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log

        self.meinberg = MeinbergSNMP(address, port)

        agg_params = {
            'frame_length': 10*60  # [sec]
        }
        self.agent.register_feed('m1000',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

    @inlineCallbacks
    def start_record(self, session, params=None):
        """start_record(params=None)

        OCS Process for fetching values from the M1000 via SNMP.

        The session.data object stores each unique OID with its latest status,
        decoded value, and the last time the value was retrived. This will look like
        the example here::

            >>> session.data
            {"mbgLtNgPtpPortState_1":
                {"status": 3,
                 "description": "disabled",
                 "lastGet": 1598543397.689727},
            "mbgLtNgNtpCurrentState_0":
                {"status": 1,
                 "description": "not synchronized",
                 "lastGet": 1598543363.289597},
            "mbgLtNgRefclockState_1":
                {"status": 2,
                 "description": "not synchronized",
                 "lastGet": 1598543359.6326838},
            "mbgLtNgSysPsStatus_1":
                {"status": 2,
                 "description": "up",
                 "lastGet": 1598543359.6326838},
            "mbgLtNgSysPsStatus_2":
                {"status": 2,
                 "description": "up",
                 "lastGet": 1598543359.6326838},
            "mbgLtNgEthPortLinkState_1":
                {"status": 1,
                 "description": "up",
                 "lastGet": 1598543359.6326838}}

        Note that session.data is populated within the self.meinberg.get_intervals() call.

        """
        if params is None:
            params = {}

        self.is_streaming = True

        while self.is_streaming:
            yield self.meinberg.get_intervals(session)
            self.log.debug("{data}", data=session.data)
            yield dsleep(0.1)

        return True, "Finished Recording"

    def stop_record(self, session, params=None):
        """stop_record(params=None)

        Stop method associated with start_record process.

        """
        self.is_streaming = False
        return True, "Stopping Recording"


def make_parser(parser=None):
    """Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.

    """
    if parser is None:
        parser = argparse.ArgumentParser()

    # Add options specific to this agent.
    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--auto-start", default=True, type=bool,
                        help="Automatically start polling for data at " +
                        "Agent startup.")
    pgroup.add_argument("--address", help="Address to listen to.")
    pgroup.add_argument("--port", default=161,
                        help="Port to listen on.")

    return parser


if __name__ == "__main__":
    # Start logging
    txaio.start_logging(level=environ.get("LOGLEVEL", "info"))

    # Get the default ocs agrument parser
    site_parser = site_config.add_arguments()
    parser = make_parser(site_parser)

    # Parse commandline
    args = parser.parse_args()

    site_config.reparse_args(args, "MeinbergM1000Agent")

    agent, runner = ocs_agent.init_site_agent(args)
    listener = MeinbergM1000Agent(agent,
                                  address=args.address,
                                  port=int(args.port))

    agent.register_process("record",
                           listener.start_record,
                           listener.stop_record,
                           startup=bool(args.auto_start), blocking=False)

    runner.run(agent, auto_reconnect=True)
