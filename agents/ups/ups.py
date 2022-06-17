import numpy as np
from numpy import random
import datetime
import time
import os
from os import environ

from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.util import sleep as dsleep
from twisted.internet import reactor
import argparse
import txaio
from ocs.ocs_twisted import TimeoutLock

from socs.snmp import SNMPTwister

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


class UPS_SNMP:
    """UPS SNMP communicator. Handles communication with and decoding of
    values from the UPS.

    Parameters
    ----------
    address : str
        Address of the UPS.
    port : int
        SNMP port to issue GETs to, default to 161.
    version : int
        SNMP version for communication (1, 2, or 3), defaults to 3.
    Attributes
    ----------
    address : str
        Address of the UPS.
    port : int
        SNMP port to issue GETs to.
    snmp : socs.snmp.SNMPTwister
        snmp handler from SOCS
    mib_timings : list
        list of dicts describing the SNMP OIDs to check, and at which
        intervals. Each dict contains the keys "oid", "interval", and
        "lastGet". The corresponding values are of types tuple, integer, and
        float, respectively. "lastGet" is initialized as None, since no SNMP
        GET commands have been issued.
    oid_cache : dict
        Cache of OID values and corresponding decoded values. Meant to be
        passed directly to session.data.
    """

    def __init__(self, address, port=161, version=3):
        self.log = txaio.make_logger()
        self.address = address
        self.port = port
        self.version = version
        self.snmp = SNMPTwister(address, port)

        # OIDs and how often to query them
        self.mib_timings = [{"oid": ('UPS-MIB', 'upsIdentManufacturer', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsIdentModel', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsBatteryStatus', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsSecondsOnBattery', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsEstimatedMinutesRemaining', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsEstimatedChargeRemaining', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsBatteryVoltage', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsBatteryCurrent', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsBatteryTemperature', 0),
                             "interval": 60,
                             "lastGet": None},
                            {"oid": ('UPS-MIB', 'upsOutputSource', 0),
                             "interval": 60,
                             "lastGet": None}]

        self.oid_cache = {}

        # Determine unique interval values
        self.interval_groups = list({x['interval'] for x in self.mib_timings})

    def _build_get_list(self, interval):
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

    def _extract_oid_field_and_value(self, get_result):
        """Extract field names and OID values from SNMP GET results.
        The ObjectType objects returned from pysnmp interactions contain the
        info we want to use for field names, specifically the OID and associated
        integer for uniquely identifying duplicate OIDs, as well as the value of the
        OID, which we want to save.
        Here we use the prettyPrint() method to get the OID name, requiring
        some string manipulation. We also just grab the hidden ._value
        directly, as this seemed the cleanest way to get an actual value of a
        normal type. Without doing this we get a pysnmp defined Integer32 or
        DisplayString, which were akward to handle, particularly the
        DisplayString.
        Parameters
        ----------
        get_result : pysnmp.smi.rfc1902.ObjectType
            Result from a pysnmp GET command.
        Returns
        -------
        field_name : str
            Field name for an OID, i.e. 'outletStatus_0'
        oid_value : int or str
            Associated value for the OID. Returns None if not an int or str
        oid_description : str
            String description of the OID value.
        """
        # OID from SNMP GET
        oid = get_result[0].prettyPrint()
        # Makes something like 'IBOOTPDU-MIB::outletStatus.1'
        # look like 'outletStatus_1'
        field_name = oid.split("::")[1].replace('.', '_')

        # Grab OID value, mostly these are integers
        oid_value = get_result[1]._value
        oid_description = get_result[1].prettyPrint()

        self.log.debug("{o} {value}",
                       o=field_name,
                       value=oid_value)

        # Decode string values
        if isinstance(oid_value, bytes):
            oid_value = oid_value.decode("utf-8")

        # I don't expect any other types at the moment, but just in case.
        if not isinstance(oid_value, (int, bytes, str)):
            self.log.error("{oid} is of unknown and unhandled type "
                           + "{oid_type}. Returning None.",
                           oid=oid, oid_type=type(oid_value))
            oid_value = None

        return field_name, oid_value, oid_description

    def update_cache(self, get_result, timestamp):
        """Update the OID Value Cache.
        The OID Value Cache is used to store each unique OID, the latest value,
        the associated decoded string, and the last time the OID was queried from the
        UPS.
        The cache consists of a dictionary, with the unique OIDs as keys, and
        another dictionary as the value. Each of these nested dictionaries contains the
        OID values, description (decoded string), and last query time. An
        example for a single OID::
            {"upsBatteryStatus":
                {"status": 2,
                 "lastGet": 1598543397.689727,
                 "description": "batteryNormal"}}
        Additionally there is connection status information under::
            {"ups_connection":
                {"last_attempt": 1598543359.6326838,
                "connected": True}
        This method modifies self.oid_cache.
        Parameters
        ----------
        get_result : pysnmp.smi.rfc1902.ObjectType
            Result from a pysnmp GET command.
        timestamp : float
            Timestamp for when the SNMP GET was issued.
        """
        try:
            for item in get_result:
                field_name, oid_value, oid_description = self._extract_oid_field_and_value(item)
                if oid_value is None:
                    continue

                # Update OID Cache for session.data
                self.oid_cache[field_name] = {"status": oid_value}
                self.oid_cache[field_name]["lastGet"] = timestamp
                self.oid_cache[field_name]["description"] = oid_description
                self.oid_cache['ups_connection'] = {'last_attempt': time.time(),
                                                      'connected': True}
        # This is a TypeError due to nothing coming back from the yield in
        # run_snmp_get, so get_result is None here and can't be iterated.
        except TypeError:
            self.oid_cache['ups_connection'] = {'last_attempt': time.time(),
                                                  'connected': False}
            raise ConnectionError('No SNMP response. Check your connection.')

    def _build_message(self, interval, get_result, time):
        """Build the message for publication on an OCS Feed.
        For a given MIB timing interval, build a message for Feed publication.
        Each interval contains only the OIDs that are sampled on the same timing
        interval. We split by interval since the available fields cannot change
        within a block over time.
        Parameters
        ----------
        interval : int
            Timing interval in seconds
        get_result : pysnmp.smi.rfc1902.ObjectType
            Result from a pysnmp GET command.
        time : float
            Timestamp for when the SNMP GET was issued.
        Returns
        -------
        message : dict
            OCS Feed formatted message for publishing
        """
        message = {
            'block_name': f'UPS_{interval}',
            'timestamp': time,
            'data': {}
        }

        for item in get_result:
            field_name, oid_value, oid_description = self._extract_oid_field_and_value(item)

            if oid_value is None:
                continue
            
            message['data'][field_name] = oid_value
            message['data'][field_name + "_description"] = oid_description

        return message

    @inlineCallbacks
    def run_snmp_get(self, session):
        """Peform the main data acquisition steps, issuing SNMP GET commands
        for each OID, depending on when we last queried them.
        These steps are performed for each group of OIDs in the same timing
        interval. We first build a list of OIDs to query. We then query them, update
        the local cache which is passed to the session.data object, build an OCS
        formatted message, and publish that message on the OCS Feed.
        If no OID should be queried yet we continue, expecting the Agent to
        handle any waiting that should be done between queries.
        """
        for interval in self.interval_groups:
            # Create list of OIDs to GET based on last time we checked them
            get_list = self._build_get_list(interval)

            # empty if an interval of time hasn't passed since last GET
            if not get_list:
                continue

            # Issue SNMP GET command
            result = yield self.snmp.get(get_list, self.version)
            read_time = time.time()

            # Do not publish if UPS connection has dropped
            try:
                self.update_cache(result, read_time)
                message = self._build_message(interval, result, read_time)

                # Update lastGet time
                for mib in self.mib_timings:
                    if mib['oid'] in get_list:
                        mib['lastGet'] = read_time

                self.log.debug("{msg}", msg=message)
                session.app.publish_to_feed('UPS', message)
            except ConnectionError as e:
                self.log.error(f'{e}')

            # Update connection status in session.data
            session.data = self.oid_cache


class UPSAgent:
    """Monitor the UPS system via SNMP.
    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the UPS.
    port : int
        SNMP port to issue GETs to, default to 161.
    version : int
        SNMP version for communication (1, 2, or 3), defaults to 3.
    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the UPS. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, address, port=161, version=3):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.log.info(f'Using SNMP version {version}.')
        self.UPS = UPS_SNMP(address, port, version)

        agg_params = {
            'frame_length': 60  # [sec]
        }
        self.agent.register_feed('ups',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()
        **Process** - Fetch values from the UPS via SNMP.
        """
        if params is None:
            params = {}

        # Make an initial attempt at connection.
        # Allows us to fail early if misconfigured.
        yield self.UPS.run_snmp_get(session)
        if not self.UPS.oid_cache['ups_connection'].get('connected', False):
            self.log.error('No initial SNMP response.')
            self.log.error('Either there is a network connection issue, '
                           + 'or maybe you are using the wrong SNMP '
                           + 'version. Either way, we are exiting.')

            reactor.callFromThread(reactor.stop)
            return False, 'acq process failed - No connection to UPS'

        self.is_streaming = True

        while self.is_streaming:
            yield self.UPS.run_snmp_get(session)
            self.log.debug("{data}", data=session.data)
            yield dsleep(1)

        return True, "Finished Recording"

    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        self.is_streaming = False
        return True, "Stopping Recording"  


def add_agent_args(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--auto-start", default=True, type=bool,
                        help="Automatically start polling for data at "
                        + "Agent startup.")
    pgroup.add_argument("--address", help="Address to listen to.")
    pgroup.add_argument("--port", default=161,
                        help="Port to listen on.")
    pgroup.add_argument("--snmp-version", default='3', choices=['1', '2', '3'],
                        help="SNMP version for communication. Must match "
                             + "configuration on the UPS.")

    return parser


if __name__ == "__main__":
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='UPSAgent', parser=parser)

    agent, runner = ocs_agent.init_site_agent(args)
    p = UPSAgent(agent,
                      address=args.address,
                      port=int(args.port),
                      version=int(args.snmp_version))

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=bool(args.auto_start), blocking=False)

    runner.run(agent, auto_reconnect=True)