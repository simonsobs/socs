import argparse
import os
import time

import txaio
from autobahn.twisted.util import sleep as dsleep
from ocs import ocs_agent, site_config
from ocs.ocs_twisted import TimeoutLock
from twisted.internet.defer import inlineCallbacks

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


def _build_message(get_result, time):
    """Build the message for publication on an OCS Feed.

    Parameters
    ----------
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
        'block_name': 'syncbox',
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

        {"mbgSyncboxN2XCurrentRefSource_0": {"status": 'PTP',
                                             "description": 'PTP'}}

    Additionally there is connection status and timestamp information under::

         "syncbox_connection": {"last_attempt": 1598543359.6326838,
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
        oid_cache['syncbox_connection'] = {'last_attempt': time.time(),
                                           'connected': False}
        return oid_cache

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)
        if oid_value is None:
            continue

        # Update OID Cache for session.data
        oid_cache[field_name] = {"status": oid_value}
        oid_cache[field_name]["description"] = oid_description
        oid_cache['syncbox_connection'] = {'last_attempt': time.time(),
                                           'connected': True}
        oid_cache['timestamp'] = timestamp

    return oid_cache


class MeinbergSyncboxAgent:
    """Monitor the syncbox system via SNMP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the syncbox.
    port : int
        SNMP port to issue GETs to, default to 161.
    version : int
        SNMP version for communication (1, 2, or 3), defaults to 1.
    outputs : list of ints
        List of outputs to monitor.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the syncbox. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, address, port=161, version=1, outputs=[1, 2, 3]):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.log.info(f'Using SNMP version {version}.')
        self.version = version
        self.address = address
        self.snmp = SNMPTwister(address, port)
        self.connected = True

        self.lastGet = 0
        self.sample_period = 60

        # Create the list of OIDs to send get commands
        oids = ['mbgSyncboxN2XSerialNumber',
                'mbgSyncboxN2XFirmwareRevision',
                'mbgSyncboxN2XSystemTime',
                'mbgSyncboxN2XCurrentRefSource',
                'mbgSyncboxN2XPtpProfile',
                'mbgSyncboxN2XPtpNwProt',
                'mbgSyncboxN2XPtpPortState',
                'mbgSyncboxN2XPtpDelayMechanism',
                'mbgSyncboxN2XPtpDelayRequestInterval',
                'mbgSyncboxN2XPtpTimescale',
                'mbgSyncboxN2XPtpUTCOffset',
                'mbgSyncboxN2XPtpLeapSecondAnnounced',
                'mbgSyncboxN2XPtpGrandmasterClockID',
                'mbgSyncboxN2XPtpGrandmasterTimesource',
                'mbgSyncboxN2XPtpGrandmasterPriority1',
                'mbgSyncboxN2XPtpGrandmasterClockClass',
                'mbgSyncboxN2XPtpGrandmasterClockAccuracy',
                'mbgSyncboxN2XPtpGrandmasterClockVariance',
                'mbgSyncboxN2XPtpOffsetToGrandmaster',
                'mbgSyncboxN2XPtpMeanPathDelay']
        output_oids = ['mbgSyncboxN2XOutputMode']
        mib = 'MBG-SYNCBOX-N2X-MIB'

        self.get_list = []

        # Create the lists of OIDs to send get commands
        for oid in oids:
            self.get_list.append([(mib, oid, 0)])

        for out in outputs:
            for oid in output_oids:
                self.get_list.append([(mib, oid, out - 1)])

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('syncbox',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from the syncbox via SNMP.

        Parameters
        ----------
        test_mode : bool, optional
            Run the Process loop only once. Meant only for testing.
            Default is False.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'mbgSyncboxN2XSerialNumber_0':
                {'status': '009811006890',
                 'description': '009811006890'},
            'mbgSyncboxN2XFirmwareRevision_0':
                {'status': '1.20 ',
                 'description': '1.20 '},
            'mbgSyncboxN2XSystemTime_0':
                {'status': '2023-10-28 14:25:54 UTC',
                 'description': '2023-10-28 14:25:54 UTC'},
            'mbgSyncboxN2XCurrentRefSource_0':
                {'status': 'PTP',
                 'description': 'PTP'},
            'mbgSyncboxN2XPtpProfile_0':
                {'status': 0,
                 'description': 'none'},
            'mbgSyncboxN2XPtpNwProt_0':
                {'status': 1,
                 'description': 'ipv4'},
            'mbgSyncboxN2XPtpPortState_0':
                {'status': 9,
                 'description': 'slave'},
            'mbgSyncboxN2XPtpDelayMechanism_0':
                {'status': 0,
                 'description': 'e2e'},
            'mbgSyncboxN2XPtpDelayRequestInterval_0':
                {'status': 1,
                 'description': '1'},
            'mbgSyncboxN2XPtpTimescale_0':
                {'status': 0,
                 'description': 'tai'},
            'mbgSyncboxN2XPtpUTCOffset_0':
                {'status': '37 sec',
                 'description': '37 sec'},
            'mbgSyncboxN2XPtpLeapSecondAnnounced_0':
                {'status': 'no',
                 'description': 'no'},
            'mbgSyncboxN2XPtpGrandmasterClockID_0':
                {'status': 'EC:46:70:FF:FE:0A:AB:FE',
                 'description': 'EC:46:70:FF:FE:0A:AB:FE'},
            'mbgSyncboxN2XPtpGrandmasterTimesource_0':
                {'status': 32,
                 'description': 'gps'},
            'mbgSyncboxN2XPtpGrandmasterPriority1_0':
                {'status': 64,
                 'description': '64'},
            'mbgSyncboxN2XPtpGrandmasterClockClass_0':
                {'status': 6,
                 'description': '6'},
            'mbgSyncboxN2XPtpGrandmasterClockAccuracy_0':
                {'status': 33, 'description':
                 'accurateToWithin100ns'},
            'mbgSyncboxN2XPtpGrandmasterClockVariance_0':
                {'status': 13563,
                 'description': '13563'},
            'mbgSyncboxN2XPtpOffsetToGrandmaster_0':
                {'status': '10 ns',
                 'description': '10 ns'},
            'mbgSyncboxN2XPtpMeanPathDelay_0':
                {'status': '875 ns',
                 'description': '875 ns'},
            'mbgSyncboxN2XOutputMode_1':
                {'status': 4,
                 'description': 'pulsePerSecond'},
             'syncbox_connection':
                {'last_attempt': 1656085022.680916,
                 'connected': True},
             'timestamp': 1656085022.680916,
             'address': '10.10.10.50'}

        Some relevant options and units for the above OIDs::

            mbgSyncboxN2XPtpProfile::
                Options:: none(0),
                          power(1),
                          telecom(2)
            mbgSyncboxN2XPtpNwProt::
                Options:: unknown(0),
                          ipv4(1),
                          ipv6(2),
                          ieee802-3(3),
                          deviceNet(4),
                          controlNet(5),
                          profiNet(6)
            mbgSyncboxN2XPtpPortState::
                Options:: uninitialized(0),
                          initializing(1),
                          faulty(2),
                          disabled(3),
                          listening(4),
                          preMaster(5),
                          master(6),
                          passive(7),
                          uncalibrated(8),
                          slave(9)
            mbgSyncboxN2XPtpDelayMechanism::
                Options:: e2e(0),
                          p2p(1)
            mbgSyncboxN2XPtpTimescale::
                Options:: tai(0),
                          arb(1)
            mbgSyncboxN2XPtpGrandmasterTimesource::
                Options:: atomicClock(16),
                          gps(32),
                          terrestrialRadio(48),
                          ptp(64),
                          ntp(80),
                          handSet(96),
                          other(144),
                          internalOscillator(160)
            mbgSyncboxN2XPtpGrandmasterClockAccuracy::
                Options:: accurateToWithin25ns(32),
                          accurateToWithin100ns(33),
                          accurateToWithin250ns(34),
                          accurateToWithin1us(35),
                          accurateToWithin2Point5us(36),
                          accurateToWithin10us(37),
                          accurateToWithin25us(38),
                          accurateToWithin100us(39),
                          accurateToWithin250us(40),
                          accurateToWithin1ms(41),
                          accurateToWithin2Point5ms(42),
                          accurateToWithin10ms(43),
                          accurateToWithin25ms(44),
                          accurateToWithin100ms(45),
                          accurateToWithin250ms(46),
                          accurateToWithin1s(47),
                          accurateToWithin10s(48),
                          accurateToGreaterThan10s(49)
        """

        self.is_streaming = True
        while self.is_streaming:
            yield dsleep(1)
            if not self.connected:
                self.log.error('No SNMP response. Check your connection!')
                self.log.info('Trying to reconnect.')

            read_time = time.time()

            # Check if sample period has passed before getting status
            if (read_time - self.lastGet) < self.sample_period:
                continue

            # Issue SNMP GET command
            # The syncbox has a unique case this requires issuing GET commands
            # one by one or else it will return the same data for each OID
            get_result = []
            for get in self.get_list:
                result = yield self.snmp.get(get, self.version)
                if result is None:
                    self.connected = False
                    session.data['syncbox_connection'] = {'last_attempt': time.time(),
                                                          'connected': False}
                    break
                get_result.extend(result)
                self.connected = True
            if not self.connected:
                session.degraded = True
                continue
            session.degraded = False

            # Do not publish if syncbox connection has dropped
            try:
                # Update session.data
                oid_cache = update_cache(get_result, read_time)
                oid_cache['address'] = self.address
                session.data = oid_cache
                self.log.info("{data}", data=session.data)

                self.lastGet = time.time()
                # Publish to feed
                message = _build_message(get_result, read_time)
                self.log.info("{msg}", msg=message)
                session.app.publish_to_feed('syncbox', message)
            except Exception as e:
                self.log.error(f'{e}')
                yield dsleep(1)

            if params['test_mode']:
                break

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
                             + "configuration on the syncbox.")
    pgroup.add_argument("--mode", default='acq', choices=['acq', 'test'])
    pgroup.add_argument("--outputs", nargs='+', default=[1, 2, 3], type=int,
                        help="Syncbox outputs to monitor. Defaults to [1,2,3].")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='MeinbergSyncboxAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = MeinbergSyncboxAgent(agent,
                             address=args.address,
                             port=int(args.port),
                             version=int(args.snmp_version),
                             outputs=args.outputs)

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params, blocking=False)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
