import argparse
import os
import time
import sys
import signal

import txaio
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet.defer import inlineCallbacks

import socs
from socs.snmp import SNMPTwister

# For logging
txaio.use_twisted()


def _extract_oid_field_and_value(get_result):
    """Extract field names and OID values from SNMP GET results.

    The ObjectType objects returned from pysnmp interactions contain the
    info we want to use for field names, specifically the OID and associated
    integer for uniquely identifying duplicate OIDs, as well as the value of the
    OID, which we want to save.

    Here we use the prettyPrint() method to get the OID name, requiring
    some string manipulation. We also just grab the hidden ._value
    directly, as this seemed the cleanest way to get an actual value of a
    normal type. Without doing this we get a pysnmp defined Integer32 or
    DisplayString, which were awkward to handle, particularly the
    DisplayString.

    Parameters
    ----------
    get_result : pysnmp.smi.rfc1902.ObjectType
        Result from a pysnmp GET command.

    Returns
    -------
    field_name : str
        Field name for an OID, i.e. 'outletStatus_1'
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

    # Decode string values
    if isinstance(oid_value, bytes):
        oid_value = oid_value.decode("utf-8")

    # I don't expect any other types at the moment, but just in case.
    if not isinstance(oid_value, (int, bytes, str)):
        oid_value = None

    return field_name, oid_value, oid_description


def _build_message(get_result, time, blockname):
    """Build the message for publication on an OCS Feed.

    Parameters
    ----------
    get_result : pysnmp.smi.rfc1902.ObjectType
        Result from a pysnmp GET command.
    names : list
        List of strings for outlet names
    time : float
        Timestamp for when the SNMP GET was issued.

    Returns
    -------
    message : dict
        OCS Feed formatted message for publishing
    """
    message = {
        'block_name': blockname,
        'timestamp': time,
        'data': {}
    }

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)

        if oid_value is None:
            continue

        message['data'][field_name] = oid_value
        message['data'][field_name + "_description"] = oid_description

    return message


def update_cache(get_result, timestamp):
    """Update the OID Value Cache.

    The OID Value Cache is used to store each unique OID and will be passed to
    session.data

    The cache consists of a dictionary, with the unique OIDs as keys, and
    another dictionary as the value. Each of these nested dictionaries contains
    the OID values, name, and description (decoded string). An example for a
    single OID, with connection status and timestamp information::

        {"outletStatus_0": {"status": 1,
                            "name": Outlet-1,
                            "description": "on"},
         "switch_connection": {"last_attempt": 1598543359.6326838,
                                 "connected": True},
         "timestamp": 1656085022.680916}

    Parameters
    ----------
    get_result : pysnmp.smi.rfc1902.ObjectType
        Result from a pysnmp GET command.
    timestamp : float
        Timestamp for when the SNMP GET was issued.
    """
    oid_cache = {}
    # Return disconnected if SNMP response is empty
    if get_result is None:
        oid_cache['switch_connection'] = {'last_attempt': time.time(),
                                            'connected': False}
        return oid_cache

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)
        if oid_value is None:
            continue

        # Update OID Cache for session.data
        oid_cache[field_name] = {"status": oid_value}
        oid_cache[field_name]["description"] = oid_description
        oid_cache['switch_connection'] = {'last_attempt': time.time(),
                                            'connected': True}
        oid_cache['timestamp'] = timestamp

    return oid_cache


class NetworkSwitchAgent:
    """Monitor the switch system via SNMP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the switch.
    port : int
        SNMP port to issue GETs to, default to 161.
    version : int
        SNMP version for communication (1, 2, or 3), defaults to 1.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the switch. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, address, port=161, version=1, restart_time=0):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.log.info(f'Using SNMP version {version}.')
        self.version = version
        self.address = address
        self.snmp = SNMPTwister(address, port)
        self.connected = True
        self.restart = restart_time

        self.lastGet = 0
        self.sample_period = 60

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('switch',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from the switch via SNMP.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'sysDescr_0':
                {'status': 'PLANET IGS-6325-20T4C4X Managed Switch',
                 'description': 'PLANET IGS-6325-20T4C4X Managed Switch'},
             'sysName_0':
                {'status': 'switch-office-rack3-1',
                 'description': 'switch-office-rack3-1'},
             'sysUpTime_0':
                {'status': 145661481,
                 'description': '145661481'},
             'tcpRtoAlgorithm_0':
                {'status': 1,
                 'description': 'other'},
             'tcpRtoMin_0':
                {'status': 200,
                 'description': '200'},
             'tcpRtoMax_0':
                {'status': 120000,
                 'description': '120000'},
             'tcpMaxConn_0':
                {'status': -1,
                 'description': '-1'},
             'tcpActiveOpens_0':
                {'status': 0,
                 'description': '0'},
             'tcpPassiveOpens_0':
                {'status': 72,
                 'description': '72'},
             'tcpAttemptFails_0':
                {'status': 0,
                 'description': '0'},
             'tcpEstabResets_0':
                {'status': 11,
                 'description': '11'},
             'tcpCurrEstab_0':
                {'status': 0,
                 'description': '0'},
             'tcpInSegs_0':
                {'status': 8225,
                 'description': '8225'},
             'tcpOutSegs_0':
                {'status': 8219,
                 'description': '8219'},
             'tcpRetransSegs_0':
                {'status': 0,
                 'description': '0'},
             'tcpInErrs_0':
                {'status': 0,
                 'description': '0'},
             'tcpOutRsts_0':
                {'status': 17,
                 'description': '17'},
             'switch_connection':
                {'last_attempt': 1698843214.0731778,
                 'connected': True},
             'timestamp': 1698843208.1860054
             'address': '192.168.0.100',

            Indexing for the Planet switch begins at 1000001. Then
            for each port of the switch,

             'ifOperStatus_1000001':
                {'status': 1,
                 'description': 'up'},
             'ifInOctets_1000001':
                {'status': 1094293870,
                 'description': '1094293870'},
             'ifInUcastPkts_1000001':
                {'status': 214301149,
                 'description': '214301149'},
             'ifInNUcastPkts_1000001':
                {'status': 17530164,
                 'description': '17530164'},
             'ifInDiscards_1000001':
                {'status': 0,
                 'description': '0'},
             'ifInErrors_1000001':
                {'status': 3,
                 'description': '3'},
             'ifInUnknownProtos_1000001':
                {'status': 0,
                 'description': '0'},
             'ifOutOctets_1000001':
                {'status': 3977100576,
                 'description': '3977100576'},
             'ifOutUcastPkts_1000001':
                {'status': 969211624,
                 'description': '969211624'},
             'ifOutNUcastPkts_1000001':
                {'status': 353855,
                 'description': '353855'},
             'ifOutDiscards_1000001':
                {'status': 0,
                 'description': '0'},
             'ifOutErrors_1000001':
                {'status': 0,
                 'description': '0'}}

        Some relevant options and units for the above OIDs::

            tcpRtoAlgorithm::
                Options:: other(1),    -- none of the following
                          constant(2), -- a constant rto
                          rsre(3),     -- MIL-STD-1778, Appendix B
                          vanj(4),     -- Van Jacobson's algorithm
                          rfc2988(5)   -- RFC 2988
            tcpRtoMin::
                Units:: milliseconds
            tcpRtoMax::
                Units:: milliseconds
            ifOperStatus::
                Options:: up(1),        -- ready to pass packets
                          down(2),
                          testing(3),   -- in some test mode
                          unknown(4),   -- status can not be determined
                                        -- for some reason.
                          dormant(5),
                          notPresent(6),    -- some component is missing
                          lowerLayerDown(7) -- down due to state of
                                            -- lower-layer interface(s)
            
            Refer to the various MIBs for full descriptions.
        """

        session.set_status('running')
        self.is_streaming = True
        timeout = time.time() + 60 * self.restart # exit loop after self.restart minutes
        while self.is_streaming:
            if ((timeout != 0) and (time.time() > timeout)):
                break
            yield dsleep(1)
            if not self.connected:
                self.log.error('No SNMP response. Check your connection!')
                self.log.info('Trying to reconnect.')

            read_time = time.time()

            # Check if sample period has passed before getting status
            if (read_time - self.lastGet) < self.sample_period:
                continue

            main_get_list = []
            get_list = []

            # Create the list of OIDs to send get commands
            system_oids = ['sysDescr',
                           'sysName',
                           'sysUpTime']

            for oid in system_oids:
                main_get_list.append(('SNMPv2-MIB', oid, 0))
                get_list.append(('SNMPv2-MIB', oid, 0))

            tcp_oids = ['tcpRtoAlgorithm',
                        'tcpRtoMin',
                        'tcpRtoMax',
                        'tcpMaxConn',
                        'tcpActiveOpens',
                        'tcpPassiveOpens',
                        'tcpAttemptFails',
                        'tcpEstabResets',
                        'tcpCurrEstab',
                        'tcpInSegs',
                        'tcpOutSegs',
                        'tcpRetransSegs',
                        'tcpInErrs',
                        'tcpOutRsts']

            for oid in tcp_oids:
                main_get_list.append(('TCP-MIB', oid, 0))
                get_list.append(('TCP-MIB', oid, 0))

            general_get_result = yield self.snmp.get(get_list, self.version)
            if general_get_result is None:
                self.connected = False
                continue
            self.connected = True

            if_oids = ['ifOperStatus',
                       'ifInOctets',
                       'ifInUcastPkts',
                       'ifInNUcastPkts',
                       'ifInDiscards',
                       'ifInErrors',
                       'ifInUnknownProtos',
                       'ifOutOctets',
                       'ifOutUcastPkts',
                       'ifOutNUcastPkts',
                       'ifOutDiscards',
                       'ifOutErrors']

            if_get_results = []
            # 24 interfaces ports on Planet switch
            ifs = 24
            for i in range(ifs):
                get_list = []
                for oid in if_oids:
                    main_get_list.append(('IF-MIB', oid, i + 1000001))
                    get_list.append(('IF-MIB', oid, i + 1000001))
                if_get_result = yield self.snmp.get(get_list, self.version)
                if_get_results.append(if_get_result)

            get_results = []
            # Issue SNMP GET command
            for get in main_get_list:
                get_result = yield self.snmp.get([get], self.version)
                if get_result is None:
                    self.connected = False
                    continue
                self.connected = True
                get_results.append(get_result[0])

            # Do not publish if switch connection has dropped
            try:
                # Update session.data
                session.data = update_cache(get_results, read_time)
                session.data['address'] = self.address
                self.log.debug("{data}", data=session.data)

                if not self.connected:
                    raise ConnectionError('No SNMP response. Check your connection.')

                self.lastGet = time.time()
                # Publish to feed
                if general_get_result is not None:
                    message = _build_message(general_get_result, read_time, 'switch')
                    self.log.debug("{msg}", msg=message)
                    session.app.publish_to_feed('switch', message)
                for i, result in enumerate(if_get_results):
                    if result is not None:
                        blockname = f'if_{i+1}'
                        message = _build_message(result, read_time, blockname)
                        self.log.debug("{msg}", msg=message)
                        session.app.publish_to_feed('switch', message)
            except ConnectionError as e:
                self.log.error(f'{e}')
                yield dsleep(1)
                self.log.info('Trying to reconnect.')

            if params['test_mode']:
                break

        # Exit agent to release memory
        # Add "restart: unless-stopped" to docker-compose to automatically restart container
        if ((not params['test_mode']) and (timeout != 0) and (self.is_streaming)):
            self.log.info(f"{self.restart} minutes have elasped. Exiting agent.")
            os.kill(os.getppid(), signal.SIGTERM)

        return True, "Finished Recording"

    def _stop_acq(self, session, params=None):
        """_stop_acq()
        **Task** - Stop task associated with acq process.
        """
        if self.is_streaming:
            session.set_status('stopping')
            self.is_streaming = False
            return True, "Stopping Recording"
        else:
            return False, "Acq is not currently running"


def add_agent_args(parser=None):
    """
    Build the argument parser for the Agent. Allows sphinx to automatically
    build documentation based on this function.
    """
    if parser is None:
        parser = argparse.ArgumentParser()

    pgroup = parser.add_argument_group("Agent Options")
    pgroup.add_argument("--address", help="Address to listen to.")
    pgroup.add_argument("--port", default=161,
                        help="Port to listen on.")
    pgroup.add_argument("--snmp-version", default='1', choices=['1', '2', '3'],
                        help="SNMP version for communication. Must match "
                             + "configuration on the switch.")
    pgroup.add_argument("--restart-time", default=0,
                        help="Number of minutes before restarting agent.")
    pgroup.add_argument("--mode", default='acq', choices=['acq', 'test'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='NetworkSwitchAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = NetworkSwitchAgent(agent,
                      address=args.address,
                      port=int(args.port),
                      version=int(args.snmp_version),
                      restart_time=int(args.restart_time))

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params, blocking=False)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
