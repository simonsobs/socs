import os
from os import environ

import time
import argparse
import txaio

from autobahn.twisted.util import sleep as dsleep
from twisted.internet.defer import inlineCallbacks
from pysnmp.hlapi.twisted import ObjectType, ObjectIdentity

from socs.snmp import SNMPTwister

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


class MeinbergM1000Agent:
    """Monitor the Meinberg LANTIME M1000 timing system via SNMP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the host sending the data via the G3NetworkSender
    port : int
        Port to listen for data on

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the host sending the data via the G3NetworkSender.
    port : int
        Port to listen for data on.
    is_streaming : bool
        Tracks whether or not the recorder is writing to disk. Setting to
        false stops the recording of data.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent

    """

    def __init__(self, agent, address, port=161):
        self.agent = agent
        self.address = address
        self.port = port
        self.is_streaming = False
        self.log = self.agent.log

        self.snmp = SNMPTwister(address, port)

        agg_params = {
            'frame_length': 10*60 #[sec]
        }
        self.agent.register_feed('m1000',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=1)

        self.mib_timings = [{"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)), "interval": 60, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 1)), "interval": 60, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 2)), "interval": 60, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgEthPortLinkState', 1)), "interval": 60, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockLeapSecondDate', 1)), "interval": 60*60, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgNtpCurrentState', 0)), "interval": 64, "lastGet": None},
                            {"oid": ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgPtpPortState', 1)), "interval": 3, "lastGet": None}]


    @inlineCallbacks
    def start_record(self, session, params=None):
        """start_record(params=None)

        OCS Process to start recording SMuRF data. This Process uses
        FrameRecorder, which deals with I/O, requiring this process to run in a
        worker thread. Be sure to register with blocking=True.

        """
        if params is None:
            params = {}

        self.is_streaming = True

        # Determine unique interval values
        interval_groups = list(set([x['interval'] for x in self.mib_timings]))

        while self.is_streaming:
            # Loop through interval groups and issue get commands for each
            # interval group, publishing to a block with the interval in the
            # name.
            for interval in interval_groups:
                # Create list of OIDs to GET based on last time we checked them
                get_list = []
                for mib in self.mib_timings:
                    # Select only OIDs of the same interval
                    if mib['interval'] != interval:
                        continue

                    if mib["lastGet"] is None:
                        get_list.append(mib["oid"])
                    elif time.time() - mib["lastGet"] > mib["interval"]:
                        get_list.append(mib["oid"])

                if get_list:
                    # Issue SNMP GET command
                    result = yield self.snmp.get(get_list)
                    read_time = time.time()

                if result:
                    message = {
                        'block_name': f'm1000_{interval}',
                        'timestamp': read_time,
                        'data': {}
                    }

                    for thing in result:
                        try:
                            # TODO: Change to debug
                            self.log.info("{oid} {value}",
                                          oid=thing[0].prettyPrint(),
                                          value=int(thing[1]))
                            message['data'][thing[0].prettyPrint()] = int(thing[1])
                        except ValueError:
                            self.log.warn('{oid} is of type {_type}, not int', oid=thing[1], _type=type(thing[1]))

                    # Update lastGet time
                    for mib in self.mib_timings:
                        if mib['oid'] in get_list:
                            mib['lastGet'] = read_time

                    # TODO: Change to debug
                    self.log.info("{msg}", msg=message)
                    session.app.publish_to_feed('m1000', message)

                result = []
                yield dsleep(0.1)

        #while self.is_streaming:
        #    recorder.run()

        ## Explicitly clean up when done
        #del recorder

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
                        help="Automatically start listening for data at " +
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
