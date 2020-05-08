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

    def run_thing(self, hostname):
        # twisted
        def success(args, hostname):
            (errorStatus, errorIndex, varBinds) = args
        
            if errorStatus:
                print('%s: %s at %s' % (hostname,
                                        errorStatus.prettyPrint(),
                                        errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
            else:
                for varBind in varBinds:
                    print(' = '.join([x.prettyPrint() for x in varBind]))

            return varBinds
        
        def failure(errorIndication, hostname):
            print('%s failure: %s' % (hostname, errorIndication))
        
        
        # noinspection PyUnusedLocal
        def getSysDescr(hostname):
            d = getCmd(SnmpEngine(),
                       CommunityData('public', mpModel=0),
                       UdpTransportTarget((hostname, 161)),
                       ContextData(),
                       ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)))
        
            d.addCallback(success, hostname).addErrback(failure, hostname)
        
            return d

        print(type(getSysDescr(hostname)))

        return getSysDescr(hostname)


    def try2(self, hostname):
        def success(args, hostname):
            (errorStatus, errorIndex, varBinds) = args
        
            if errorStatus:
                print('%s: %s at %s' % (hostname,
                                        errorStatus.prettyPrint(),
                                        errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
            else:
                for varBind in varBinds:
                    print(' = '.join([x.prettyPrint() for x in varBind]))
        
        
        def failure(errorIndication, hostname):
            print('%s failure: %s' % (hostname, errorIndication))
        
        
        # noinspection PyUnusedLocal
        #def getSysDescr(hostname):
        d = getCmd(SnmpEngine(),
                   CommunityData('public', mpModel=0),
                   UdpTransportTarget((hostname, 161)),
                   ContextData(),
                   ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)))
        
        d.addCallback(success, hostname).addErrback(failure, hostname)
        
        return d

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
            result = yield self.try2('10.10.10.186')
            #result = yield self.run_thing('10.10.10.186')

            #message = {
            #    'block_name': 'm1000',
            #    'timestamp': time.time(),
            #    'data': {
            #        'mbgLtNgRefclockState': int(result[1])
            #    }
            #}

            #session.app.publish_to_feed('m1000', message)

            yield dsleep(10)

        # synchronous
        # while self.is_streaming:
        #     errorIndication, errorStatus, errorIndex, varBinds = next(
        #         getCmd(SnmpEngine(),
        #                CommunityData('public', mpModel=0),
        #                UdpTransportTarget((self.address, self.port)),
        #                ContextData(),
        #                ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)))
        #     )

        #     if errorIndication:
        #         print(errorIndication)
        #     elif errorStatus:
        #         print('%s at %s' % (errorStatus.prettyPrint(),
        #                             errorIndex and varBinds[int(errorIndex) - 1][0] or '?'))
        #     else:
        #         for varBind in varBinds:
        #             print(' = '.join([x.prettyPrint() for x in varBind]))


        #     message = {
        #         'block_name': 'm1000',
        #         'timestamp': time.time(),
        #         'data': {
        #             'mbgLtNgRefclockState': int(varBind[1])
        #         }
        #     }

        #     session.app.publish_to_feed('m1000', message)

        #     time.sleep(10)

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
