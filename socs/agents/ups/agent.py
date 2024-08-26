import argparse
import os
import signal
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
        Field name for an OID, i.e. 'upsIdentModel'
    oid_value : int or str
        Associated value for the OID. Returns None if not an int or str
    oid_description : str
        String description of the OID value.
    """
    # OID from SNMP GET
    oid = get_result[0].prettyPrint()
    # Makes something like 'UPS-MIB::upsIdentModel.0'
    # look like 'upsIdentModel_0'
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
    another dictionary as the value. Each of these nested dictionaries contains the
    OID values, name, and description (decoded string). An example for a single OID::

        {"upsBatteryStatus":
            {"status": 2,
                "description": "batteryNormal"}}

    Additionally there is connection status and timestamp information under::

        {"ups_connection":
            {"last_attempt": 1598543359.6326838,
            "connected": True}
        {"timestamp": 1656085022.680916}

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
        oid_cache['ups_connection'] = {'last_attempt': time.time(),
                                       'connected': False}
        return oid_cache

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)
        if oid_value is None:
            continue

        # Update OID Cache for session.data
        oid_cache[field_name] = {"status": oid_value}
        oid_cache[field_name]["description"] = oid_description
        oid_cache['ups_connection'] = {'last_attempt': time.time(),
                                       'connected': True}
        oid_cache['timestamp'] = timestamp

    return oid_cache


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

    def __init__(self, agent, address, port=161, version=1, restart_time=0):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        self.log.info(f'Using SNMP version {version}.')
        self.version = version
        self.snmp = SNMPTwister(address, port)
        self.connected = True
        self.restart = restart_time

        self.lastGet = 0

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('ups',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from the UPS via SNMP.

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
            {'upsIdentManufacturer':
                {'description': 'Falcon'},
            'upsIdentModel':
                {'description': 'SSG3KRM-2'},
            'upsBatteryStatus':
                {'status': 2,
                 'description': 'batteryNormal'},
            'upsSecondsOnBattery':
                {'status': 0,
                 'description': 0},
            'upsEstimatedMinutesRemaining':
                {'status': 60,
                 'description': 60},
            'upsEstimatedChargeRemaining':
                {'status': 100,
                 'description': 100},
            'upsBatteryVoltage':
                {'status': 120,
                 'description': 120},
            'upsBatteryCurrent':
                {'status': 10,
                 'description': 10},
            'upsBatteryTemperature':
                {'status': 30,
                 'description': 30},
            'upsOutputSource':
                {'status': 3,
                 'description': normal},
            'upsOutputVoltage':
                {'status': 120,
                 'description': 120},
            'upsOutputCurrent':
                {'status': 10,
                 'description': 10},
            'upsOutputPower':
                {'status': 120,
                 'description': 120},
            'upsOutputPercentLoad':
                {'status': 25,
                 'description': 25}
            'upsInputVoltage':
                {'status': 120,
                 'description': 120},
            'upsInputCurrent':
                {'status': 10,
                 'description': 10},
            'upsInputTruePower':
                {'status': 120,
                 'description': 120},
            'ups_connection':
                {'last_attempt': 1656085022.680916,
                 'connected': True},
            'timestamp': 1656085022.680916}

        Some relevant options and units for the above OIDs::

            upsBatteryStatus::
                Options:: unknown(1),
                          batteryNormal(2),
                          batteryLow(3),
                          batteryDepleted(4)
            upsSecondsOnBattery::
                Note:: Zero shall be returned if the unit is not on
                       battery power.
            upsEstimatedChargeRemaining::
                Units:: percentage
            upsBatteryVoltage::
                Units:: 0.1 Volt DC
            upsBatteryCurrent::
                Units:: 0.1 Amp DC
            upsBatteryTemperature::
                Units:: degrees Centigrade
            upsOutputSource::
                Options:: other(1),
                          none(2),
                          normal(3),
                          bypass(4),
                          battery(5),
                          booster(6),
                          reducer(7)
            upsOutputVoltage::
                Units:: RMS Volts
            upsOutputCurrent::
                Units:: 0.1 RMS Amp
            upsOutputPower::
                Units:: Watts
            upsInputVoltage::
                Units:: RMS Volts
            upsInputCurrent::
                Units:: 0.1 RMS Amp
            upsInputTruePower::
                Units:: Watts
        """

        self.is_streaming = True
        timeout = time.time() + 60 * self.restart  # exit loop after self.restart minutes
        while self.is_streaming:
            if ((self.restart != 0) and (time.time() > timeout)):
                break
            yield dsleep(1)
            if not self.connected:
                self.log.error('No SNMP response. Check your connection.')
                self.log.info('Trying to reconnect.')

            read_time = time.time()

            # Check if 60 seconds has passed before getting status
            if (read_time - self.lastGet) < 60:
                continue

            main_get_list = []
            get_list = []

            # Create the list of OIDs to send get commands
            oids = ['upsIdentManufacturer',
                    'upsIdentModel',
                    'upsBatteryStatus',
                    'upsSecondsOnBattery',
                    'upsEstimatedMinutesRemaining',
                    'upsEstimatedChargeRemaining',
                    'upsBatteryVoltage',
                    'upsBatteryCurrent',
                    'upsBatteryTemperature',
                    'upsOutputSource']

            for oid in oids:
                main_get_list.append(('UPS-MIB', oid, 0))
                get_list.append(('UPS-MIB', oid, 0))

            ups_get_result = yield self.snmp.get(get_list, self.version)
            if ups_get_result is None:
                self.connected = False
                continue
            self.connected = True

            # Append input OIDs to GET list
            input_oids = ['upsInputVoltage',
                          'upsInputCurrent',
                          'upsInputTruePower']

            # Use number of input lines used to append correct number of input OIDs
            input_num_lines = [('UPS-MIB', 'upsInputNumLines', 0)]
            num_res = yield self.snmp.get(input_num_lines, self.version)
            if num_res is None:
                self.connected = False
                continue
            self.connected = True
            input_get_results = []
            inputs = num_res[0][1]._value
            for i in range(inputs):
                get_list = []
                for oid in input_oids:
                    main_get_list.append(('UPS-MIB', oid, i + 1))
                    get_list.append(('UPS-MIB', oid, i + 1))
                input_get_result = yield self.snmp.get(get_list, self.version)
                input_get_results.append(input_get_result)

            # Append output OIDs to GET list
            output_oids = ['upsOutputVoltage',
                           'upsOutputCurrent',
                           'upsOutputPower',
                           'upsOutputPercentLoad']

            # Use number of output lines used to append correct number of output OIDs
            output_num_lines = [('UPS-MIB', 'upsOutputNumLines', 0)]
            num_res = yield self.snmp.get(output_num_lines, self.version)
            if num_res is None:
                self.connected = False
                continue
            self.connected = True
            output_get_results = []
            outputs = num_res[0][1]._value
            for i in range(outputs):
                get_list = []
                for oid in output_oids:
                    main_get_list.append(('UPS-MIB', oid, i + 1))
                    get_list.append(('UPS-MIB', oid, i + 1))
                output_get_result = yield self.snmp.get(get_list, self.version)
                output_get_results.append(output_get_result)

            # Issue SNMP GET command
            get_result = yield self.snmp.get(main_get_list, self.version)
            if get_result is None:
                self.connected = False
                continue
            self.connected = True

            # Do not publish if UPS connection has dropped
            try:
                # Update session.data
                session.data = update_cache(get_result, read_time)
                self.log.debug("{data}", data=session.data)

                if not self.connected:
                    raise ConnectionError('No SNMP response. Check your connection.')

                self.lastGet = time.time()
                # Publish to feed
                if ups_get_result is not None:
                    message = _build_message(ups_get_result, read_time, 'ups')
                    self.log.debug("{msg}", msg=message)
                    session.app.publish_to_feed('ups', message)
                for i, result in enumerate(input_get_results):
                    if result is not None:
                        blockname = f'input_{i}'
                        message = _build_message(result, read_time, blockname)
                        self.log.debug("{msg}", msg=message)
                        session.app.publish_to_feed('ups', message)
                for i, result in enumerate(output_get_results):
                    if result is not None:
                        blockname = f'output_{i}'
                        message = _build_message(result, read_time, blockname)
                        self.log.debug("{msg}", msg=message)
                        session.app.publish_to_feed('ups', message)
            except ConnectionError as e:
                self.log.error(f'{e}')
                yield dsleep(1)
                self.log.info('Trying to reconnect.')

            if params['test_mode']:
                break

        # Exit agent to release memory
        # Add "restart: unless-stopped" to docker compose to automatically restart container
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
                             + "configuration on the UPS.")
    pgroup.add_argument("--restart-time", default=0,
                        help="Number of minutes before restarting agent.")
    pgroup.add_argument("--mode", choices=['acq', 'test'])

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='UPSAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = UPSAgent(agent,
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
