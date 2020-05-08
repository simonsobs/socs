import os
from os import environ

import time
import argparse
import txaio

from autobahn.twisted.util import sleep as dsleep
from twisted.internet.defer import inlineCallbacks, Deferred
from pysnmp.hlapi.twisted import getCmd, SnmpEngine, CommunityData, UdpTransportTarget,\
                                 ContextData, ObjectType, ObjectIdentity

# synchronus
#from pysnmp.hlapi import getCmd, SnmpEngine, CommunityData, UdpTransportTarget,\
#                         ContextData, ObjectType, ObjectIdentity

#from socs.agent.smurf_recorder import FrameRecorder

# For logging
txaio.use_twisted()

on_rtd = os.environ.get('READTHEDOCS') == 'True'
if not on_rtd:
    from ocs import ocs_agent, site_config


class SNMPTwister:
    """Helper class for handling SNMP communication with twisted.

    More information can be found in the pySNMP documentation. The
    `SNMP Operations`_ page is particularly helpful for understanding the setup
    of this object.

    Note: This helper currently only supports SNMPv1.

    Parameters
    ----------
    address : str
        Address of the SNMP Agent to send GET/SET requests to
    port : int
        Associated port for SNMP communication. Default is 161

    Attributes
    ----------
    snmp_engine : pysnmp.entity.engine.SnmpEngine
        PySNMP engine
    address : str
        Address of the SNMP Agent to send GET/SET requests to
    udp_transport : pysnmp.hlapi.twisted.transport.UdpTransportTarget
        UDP transport for UDP over IPv4
    log : txaio.tx.Logger
        txaio logger object

    .. _SNMP Operations:
        http://snmplabs.com/pysnmp/docs/pysnmp-hlapi-tutorial.html

    """

    def __init__(self, address, port=161):
        self.snmp_engine = SnmpEngine()
        self.address = address
        self.udp_transport = UdpTransportTarget((address, port))
        self.log = txaio.make_logger()

    def _success(self, args):
        """Success callback for getCmd.

        Taken from Twisted example for SNMPv1 from pySNMP documentation:
        http://snmplabs.com/pysnmp/examples/hlapi/twisted/contents.html

        Returns
        -------
        list
            A sequence of ObjectType class instances representing MIB variables
            returned in SNMP response.

        """
        (errorStatus, errorIndex, varBinds) = args

        if errorStatus:
            self.log.error('%s: %s at %s' % (self.address,
                                             errorStatus.prettyPrint(),
                                             errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
        else:
            for varBind in varBinds:
                self.log.debug(' = '.join([x.prettyPrint() for x in varBind]))

        return varBinds

    def _failure(self, errorIndication):
        """Failure Errback for getCmd.

        Taken from Twisted example for SNMPv1 from pySNMP documentation:
        http://snmplabs.com/pysnmp/examples/hlapi/twisted/contents.html

        """
        self.log.error('%s failure: %s' % (self.address, errorIndication))

    def get(self, oid_list):
        """Issue a getCmd to get SNMP OID states.

        Parameters
        ----------
        oid_list : list
            List of high-level MIB Object OIDs. See `Specifying MIB Objects`_ for
            more info

        .. _Specifying MIB Objects:
            http://snmplabs.com/pysnmp/docs/pysnmp-hlapi-tutorial.html#specifying-mib-object

        """
        d = getCmd(self.snmp_engine,
                   CommunityData('public', mpModel=0),  # SNMPv1
                   self.udp_transport,
                   ContextData(),
                   *oid_list)

        d.addCallback(self._success).addErrback(self._failure)

        return d


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

        self.agent.register_feed('m1000',
                                 record=True,
                                 buffer_time=1)

        self.mibs = [ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)),
                     ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockLeapSecondDate', 1))]

        self.snmp = SNMPTwister(address, port)

        self.mib_timings = [{"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1), "interval": 60, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockLeapSecondDate', 1), "interval": 60*60, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgNtpCurrentState', 0), "interval": 64, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 1), "interval": 60, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 2), "interval": 60, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgEthPortLinkState', 1), "interval": 60, "lastRead": None},
                            {"oid": ('MBG-SNMP-LTNG-MIB', 'mbgLtNgPtpPortState', 1), "interval": 3, "lastRead": None}]

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

        while self.is_streaming:
            read_list = []
            for mib in self.mib_timings:
                if mib["lastRead"] is None:
                    read_list.append(mib["oid"])
                elif time.time() - mib["lastRead"] > mib["interval"]:
                    read_list.append(mib["oid"])

            mib_objects = []
            for oid in read_list:
                mib_objects.append(ObjectType(ObjectIdentity(*oid)))

            result = yield self.snmp.get(mib_objects)
            read_time = time.time()
            for thing in result:
                print(thing[0].prettyPrint(), thing[1])

            for mib in self.mib_timings:
                if mib['oid'] in read_list:
                    mib['lastRead'] = read_time

            #message = {
            #    'block_name': 'm1000',
            #    'timestamp': time.time(),
            #    'data': {
            #        'mbgLtNgRefclockState': int(result[1])
            #    }
            #}

            #session.app.publish_to_feed('m1000', message)

            yield dsleep(1)

        #self.log.info("Data directory set to {}".format(self.data_dir))
        #self.log.info("New file every {} seconds".format(self.time_per_file))
        #self.log.info("Listening to {}".format(self.address))

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
