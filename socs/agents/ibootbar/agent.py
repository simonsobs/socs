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


def _build_message(get_result, names, time):
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
        'block_name': 'ibootbar',
        'timestamp': time,
        'data': {}
    }

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)

        if oid_value is None:
            continue

        message['data'][field_name] = oid_value
        message['data'][field_name + "_name"] = names[int(field_name[-1])]
        message['data'][field_name + "_description"] = oid_description

    return message


def update_cache(get_result, names, outlet_locked, timestamp):
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
         "ibootbar_connection": {"last_attempt": 1598543359.6326838,
                                 "connected": True},
         "timestamp": 1656085022.680916}

    Parameters
    ----------
    get_result : pysnmp.smi.rfc1902.ObjectType
        Result from a pysnmp GET command.
    names : list
        List of strings for outlet names
    outlet_locked : list of bool
        List of bool for outlets (1-8) that are locked
    timestamp : float
        Timestamp for when the SNMP GET was issued.
    """
    oid_cache = {}
    # Return disconnected if SNMP response is empty
    if get_result is None:
        oid_cache['ibootbar_connection'] = {'last_attempt': time.time(),
                                            'connected': False}
        return oid_cache

    for item in get_result:
        field_name, oid_value, oid_description = _extract_oid_field_and_value(item)
        if oid_value is None:
            continue

        # Update OID Cache for session.data
        oid_cache[field_name] = {"status": oid_value}
        oid_cache[field_name]["name"] = names[int(field_name[-1])]
        oid_cache[field_name]["locked"] = outlet_locked[int(field_name[-1])]
        oid_cache[field_name]["description"] = oid_description
        oid_cache['ibootbar_connection'] = {'last_attempt': time.time(),
                                            'connected': True}
        oid_cache['timestamp'] = timestamp

    return oid_cache


class ibootbarAgent:
    """Monitor the ibootbar system via SNMP.

    Parameters
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    address : str
        Address of the ibootbar.
    port : int
        SNMP port to issue GETs to, default to 161.
    version : int
        SNMP version for communication (1, 2, or 3), defaults to 2.
    lock_outlet : list of ints
        List of outlets to lock on agent startup. Outlets are numbered 1-8.

    Attributes
    ----------
    agent : OCSAgent
        OCSAgent object which forms this Agent
    is_streaming : bool
        Tracks whether or not the agent is actively issuing SNMP GET commands
        to the ibootbar. Setting to false stops sending commands.
    log : txaio.tx.Logger
        txaio logger object, created by the OCSAgent
    """

    def __init__(self, agent, address, port=161, version=2, lock_outlet=None):
        self.agent = agent
        self.is_streaming = False
        self.log = self.agent.log
        self.lock = TimeoutLock()

        # Initialize with locked outlets if given in args
        self.outlet_locked = [False for i in range(8)]
        if lock_outlet is not None:
            for i in range(8):
                if i + 1 in lock_outlet:
                    self.outlet_locked[i] = True
                else:
                    self.outlet_locked[i] = False

        self.log.info(f'Using SNMP version {version}.')
        self.version = version
        self.address = address
        self.snmp = SNMPTwister(address, port)
        self.connected = True

        self.lastGet = 0
        self.sample_period = 60

        agg_params = {
            'frame_length': 10 * 60  # [sec]
        }
        self.agent.register_feed('ibootbar',
                                 record=True,
                                 agg_params=agg_params,
                                 buffer_time=0)

    @ocs_agent.param('test_mode', default=False, type=bool)
    @inlineCallbacks
    def acq(self, session, params=None):
        """acq()

        **Process** - Fetch values from the ibootbar via SNMP.

        Notes
        -----
        The most recent data collected is stored in session.data in the
        structure::

            >>> response.session['data']
            {'outletStatus_0':
                {'status': 1,
                 'name': 'Outlet-1',
                 'description': 'on'},
             'outletStatus_1':
                {'status': 0,
                 'name': 'Outlet-2',
                 'description': 'off'},
             ...
             'ibootbar_connection':
                {'last_attempt': 1656085022.680916,
                 'connected': True},
             'timestamp': 1656085022.680916,
             'address': '10.10.10.50'}
        """
        # Set initial default outlet names
        # Note outlets are numbered 1-8 physically on ibootbars, OIDs are numbered 0-7
        names = ['Outlet-1', 'Outlet-2', 'Outlet-3', 'Outlet-4',
                 'Outlet-5', 'Outlet-6', 'Outlet-7', 'Outlet-8']

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

            get_list = []
            name_list = []
            names = []

            # Create the lists of OIDs to send get commands
            for i in range(8):
                get_list.append(('IBOOTPDU-MIB', 'outletStatus', i))
                name_list.append(('IBOOTPDU-MIB', 'outletName', i))

            # Issue SNMP GET commands
            get_result = yield self.snmp.get(get_list, self.version)
            if get_result is None:
                self.connected = False
                session.data['ibootbar_connection'] = {'last_attempt': time.time(),
                                                       'connected': False}
                continue
            self.connected = True

            name_result = yield self.snmp.get(name_list, self.version)
            if name_result is None:
                self.connected = False
                session.data['ibootbar_connection'] = {'last_attempt': time.time(),
                                                       'connected': False}
                continue
            self.connected = True
            for item in name_result:
                names.append(item[1].prettyPrint())

            # Do not publish if ibootbar connection has dropped
            try:
                # Update session.data
                oid_cache = update_cache(get_result, names, self.outlet_locked, read_time)
                oid_cache['address'] = self.address
                session.data = oid_cache
                self.log.debug("{data}", data=session.data)

                self.lastGet = time.time()
                # Publish to feed
                message = _build_message(get_result, names, read_time)
                self.log.debug("{msg}", msg=message)
                session.app.publish_to_feed('ibootbar', message)
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

    @ocs_agent.param('outlet', choices=[1, 2, 3, 4, 5, 6, 7, 8])
    @ocs_agent.param('state', choices=['on', 'off'])
    @inlineCallbacks
    def set_outlet(self, session, params=None):
        """set_outlet(outlet, state)

        **Task** - Set a particular outlet to on/off.

        Parameters
        ----------
        outlet : int
            Outlet number to set. Choices are 1-8 (physical outlets).
        state : str
            State to set outlet to, which may be 'on' or 'off'
        """
        with self.lock.acquire_timeout(3, job='set_outlet') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            # Check if outlet is locked
            outlet_id = params['outlet'] - 1
            if self.outlet_locked[outlet_id]:
                return False, 'Outlet {} is locked. Cannot turn outlet on/off.'.format(params['outlet'])

            # Convert given state parameter to integer
            if params['state'] == 'on':
                state = 1
            else:
                state = 0

            # Issue SNMP SET command to given outlet
            outlet = [('IBOOTPDU-MIB', 'outletControl', outlet_id)]
            setcmd = yield self.snmp.set(outlet, self.version, state)
            self.log.info('{}'.format(setcmd))

        # Force SNMP GET status commands by rewinding the lastGet time by sample period
        self.lastGet = self.lastGet - self.sample_period

        return True, 'Set outlet {} to {}'.\
            format(params['outlet'], params['state'])

    @ocs_agent.param('outlet', choices=[1, 2, 3, 4, 5, 6, 7, 8])
    @ocs_agent.param('cycle_time', default=10, type=int)
    @inlineCallbacks
    def cycle_outlet(self, session, params=None):
        """cycle_outlet(outlet, cycle_time=10)

        **Task** - Cycle a particular outlet for given amount of seconds.

        Parameters
        ----------
        outlet : int
            Outlet number to cycle. Choices are 1-8 (physical outlets).
        cycle_time : int
            The amount of seconds to cycle an outlet. Default is 10 seconds.
        """
        with self.lock.acquire_timeout(3, job='cycle_outlet') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            # Check if outlet is locked
            outlet_id = params['outlet'] - 1
            if self.outlet_locked[outlet_id]:
                return False, 'Outlet {} is locked. Cannot cycle outlet.'.format(params['outlet'])

            # Issue SNMP SET command for cycle time
            set_cycle = [('IBOOTPDU-MIB', 'outletCycleTime', outlet_id)]
            setcmd1 = yield self.snmp.set(set_cycle, self.version, params['cycle_time'])
            self.log.info('{}'.format(setcmd1))

            # Issue SNMP SET command to given outlet
            outlet = [('IBOOTPDU-MIB', 'outletControl', outlet_id)]
            setcmd2 = yield self.snmp.set(outlet, self.version, 2)
            self.log.info('{}'.format(setcmd2))
            self.log.info('Cycling outlet {} for {} seconds'.
                          format(outlet_id, params['cycle_time']))

        # Force SNMP GET status commands throughout the cycle time
        for i in range(params['cycle_time'] + 1):
            self.lastGet = self.lastGet - self.sample_period
            yield dsleep(1)

        return True, 'Cycled outlet {} for {} seconds'.\
            format(params['outlet'], params['cycle_time'])

    @ocs_agent.param('_')
    @inlineCallbacks
    def set_initial_state(self, session, params=None):
        """set_initial_state()

        **Task** - Set outlets to their initial states.

        Performs a software reboot. The outlets are then set to their
        respective initial states. This takes about 30 seconds.
        """
        with self.lock.acquire_timeout(3, job='reboot') as acquired:
            if not acquired:
                return False, "Could not acquire lock"

            # Send SNMP SET command to set rebootSystem to True
            reboot = [('IBOOTPDU-MIB', 'rebootSystem', 0)]
            setcmd = yield self.snmp.set(reboot, self.version, 1)
            self.log.info('{}'.format(setcmd))

        # Force SNMP GET status commands
        self.lastGet = self.lastGet - self.sample_period

        return True, 'Rebooting. Outlets will be set to their initial states.'

    @ocs_agent.param('outlet', choices=[1, 2, 3, 4, 5, 6, 7, 8])
    @ocs_agent.param('lock', choices=[True, False])
    def lock_outlet(self, session, params=None):
        """lock_outlet(outlet, lock)

        **Task** - Lock/unlocks a particular outlet, preventing change of state.

        Parameters
        ----------
        outlet : int
            Outlet number to lock/unlock. Choices are 1-8 (physical outlets).
        lock : bool
            Set to true to lock, set to false to unlock
        """
        with self.lock.acquire_timeout(3, job='lock_outlet') as acquired:
            if not acquired:
                return False, "Could not acquire lock"
            # Lock/unlock specific outlet
            outlet = params['outlet'] - 1
            if params['lock']:
                self.outlet_locked[outlet] = True
            elif not params['lock']:
                self.outlet_locked[outlet] = False

        return True, 'Set outlet {} lock to {}'.\
            format(params['outlet'], params['lock'])


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
    pgroup.add_argument("--snmp-version", default='2', choices=['1', '2', '3'],
                        help="SNMP version for communication. Must match "
                             + "configuration on the ibootbar.")
    pgroup.add_argument("--mode", default='acq', choices=['acq', 'test'])
    pgroup.add_argument("--lock-outlet", nargs='+', type=int,
                        help="List of outlets to lock on startup.")

    return parser


def main(args=None):
    # Start logging
    txaio.start_logging(level=os.environ.get("LOGLEVEL", "info"))

    parser = add_agent_args()
    args = site_config.parse_args(agent_class='ibootbarAgent',
                                  parser=parser,
                                  args=args)

    if args.mode == 'acq':
        init_params = True
    elif args.mode == 'test':
        init_params = False

    agent, runner = ocs_agent.init_site_agent(args)
    p = ibootbarAgent(agent,
                      address=args.address,
                      port=int(args.port),
                      version=int(args.snmp_version),
                      lock_outlet=args.lock_outlet)

    agent.register_process("acq",
                           p.acq,
                           p._stop_acq,
                           startup=init_params, blocking=False)

    agent.register_task("set_outlet", p.set_outlet, blocking=False)
    agent.register_task("cycle_outlet", p.cycle_outlet, blocking=False)
    agent.register_task("set_initial_state", p.set_initial_state, blocking=False)
    agent.register_task("lock_outlet", p.lock_outlet, blocking=False)

    runner.run(agent, auto_reconnect=True)


if __name__ == "__main__":
    main()
