import os

import txaio
from pysnmp.hlapi.v3arch.asyncio import (CommunityData, ContextData, ObjectIdentity,
                                         ObjectType, SnmpEngine, UdpTransportTarget,
                                         UsmUserData, get_cmd, set_cmd)

from socs import mibs

# For logging
txaio.use_asyncio()


MIB_SOURCE = f"{os.path.dirname(mibs.__file__)}"


class SNMPInterface:
    """Helper class for handling SNMP communication.

    More information can be found in the pySNMP documentation: `PySNMP Examples`_

    .. _PySNMP Examples: https://docs.lextudio.com/pysnmp/v7.1/examples/

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
    port : int
        Associated port for SNMP communication. Default is 161
    log : txaio.tx.Logger
        txaio logger object

    """

    def __init__(self, address, port=161):
        self.snmp_engine = SnmpEngine()
        self.address = address
        self.port = port
        self.log = txaio.make_logger()

    async def get(self, oid_list, version):
        """Issue a get_cmd to get SNMP OID states.

        Example
        -------
        >>> snmp = SNMPInterface('localhost', 161)
        >>> snmp.get([ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB',
                                                'mbgLtNgRefclockState',
                                                1)),
                      ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB',
                                                'mbgLtNgRefclockLeapSecondDate',
                                                1))])

        >>> snmp = SNMPInterface('localhost', 161)
        >>> result = snmp.get([('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1),
                               ('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockLeapSecondDate', 1)])
        >>> # Simply printing the returned object shows a nice string
        >>> print(result[0])
        MBG-SNMP-LTNG-MIB::mbgLtNgRefclockState.1 = notSynchronized
        >>> # The corresponding integer value is hidden within the returned object
        >>> print(result[0][1]._value)
        2

        Parameters
        ----------
        oid_list : list
            List of high-level MIB Object OIDs. The list elements should either be
            ObjectType, or tuples which define the OIDs, as shown in the
            example above. See `Specifying MIB object`_ for more info.

            .. _Specifying MIB Object:
               https://snmplabs.thola.io/pysnmp/docs/pysnmp-hlapi-tutorial.html#specifying-mib-object
        version : int
            SNMP version for communicaton (1, 2, or 3). All versions supported
            here without auth or privacy. If using v3 the configured username
            on the SNMP device should be 'ocs'. For details on version
            implementation in pysnmp see `SNMP Versions`_.

            .. _SNMP Versions:
               https://snmplabs.thola.io/pysnmp/examples/hlapi/asyncore/sync/manager/cmdgen/snmp-versions.html

        Returns
        -------
        list
            A sequence of ObjectType class instances representing MIB variables
            returned in SNMP response.

        """
        oid_list = [ObjectType(ObjectIdentity(*x).addMibSource(MIB_SOURCE))
                    if isinstance(x, tuple)
                    else x
                    for x
                    in oid_list]

        if version == 1:
            version_object = CommunityData('public', mpModel=0)  # SNMPv1
        elif version == 2:
            version_object = CommunityData('public')  # SNMPv2c
        elif version == 3:
            version_object = UsmUserData('ocs')  # SNMPv3 (no auth, no privacy)
        else:
            raise ValueError(f'SNMP version {version} not supported.')

        iterator = get_cmd(self.snmp_engine,
                           version_object,
                           await UdpTransportTarget.create((self.address, self.port)),
                           ContextData(),
                           *oid_list)

        error_indication, error_status, error_index, var_binds = await iterator

        if error_indication:
            self.log.error('%s failure: %s' % (self.address, error_indication))
        elif error_status:
            self.log.error('%s: %s at %s' % (self.address,
                                             error_status.prettyPrint(),
                                             error_index
                                             and var_binds[int(error_index) - 1][0] or '?'))
        else:
            for var in var_binds:
                self.log.debug(' = '.join([x.prettyPrint() for x in var]))

        return var_binds

    async def set(self, oid_list, version, setvalue, community_name='private'):
        """Issue a set_cmd to set SNMP OID states.

        See `Modifying MIB variables`_ for more info on setting OID states.

        .. _Modifying MIB variables:
           https://docs.lextudio.com/pysnmp/v7.1/examples/v1arch/asyncio/manager/cmdgen/modifying-variables

        Parameters
        ----------
        oid_list : list
            List of high-level MIB Object OIDs. The list elements should either be
            ObjectType, or tuples which define the OIDs.
        version : int
            SNMP version for communicaton (1, 2, or 3). All versions supported
            here without auth or privacy. If using v3 the configured username
            on the SNMP device should be 'ocs'.
        setvalue : int
            Integer to set OID. For example, 0 is off and 1 is on for outletControl on the iBootPDU.

        Returns
        ------
        list
            A sequence of ObjectType class instances representing MIB variables
            returned in SNMP response.

        """
        oid_list = [ObjectType(ObjectIdentity(*x).addMibSource(MIB_SOURCE), setvalue)
                    if isinstance(x, tuple)
                    else x
                    for x
                    in oid_list]

        if version == 1:
            version_object = CommunityData(community_name, mpModel=0)  # SNMPv1
        elif version == 2:
            version_object = CommunityData(community_name)  # SNMPv2c
        elif version == 3:
            version_object = UsmUserData('ocs')  # SNMPv3 (no auth, no privacy)
        else:
            raise ValueError(f'SNMP version {version} not supported.')

        iterator = set_cmd(self.snmp_engine,
                           version_object,
                           await UdpTransportTarget.create((self.address, self.port)),
                           ContextData(),
                           *oid_list)

        error_indication, error_status, error_index, var_binds = await iterator

        if error_indication:
            self.log.error('%s failure: %s' % (self.address, error_indication))
        elif error_status:
            self.log.error('%s: %s at %s' % (self.address,
                                             error_status.prettyPrint(),
                                             error_index
                                             and var_binds[int(error_index) - 1][0] or '?'))
        else:
            for var in var_binds:
                self.log.debug(' = '.join([x.prettyPrint() for x in var]))

        return var_binds
