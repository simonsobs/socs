import txaio

from pysnmp.hlapi.twisted import getCmd, SnmpEngine, CommunityData, UdpTransportTarget,\
                                 ContextData

# For logging
txaio.use_twisted()

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
        (error_status, error_index, var_binds) = args

        if error_status:
            self.log.error('%s: %s at %s' % (self.address,
                                             error_status.prettyPrint(),
                                             error_index and \
                                             var_binds[int(error_index) - 1][0] or '?'))
        else:
            for var in var_binds:
                self.log.debug(' = '.join([x.prettyPrint() for x in var]))

        return var_binds

    def _failure(self, error_indication):
        """Failure Errback for getCmd.

        Taken from Twisted example for SNMPv1 from pySNMP documentation:
        http://snmplabs.com/pysnmp/examples/hlapi/twisted/contents.html

        """
        self.log.error('%s failure: %s' % (self.address, error_indication))

    def get(self, oid_list):
        """Issue a getCmd to get SNMP OID states.

        Example
        -------
        snmp = SNMPTwister('localhost', 161)
        snmp.get([ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB',
                                            'mbgLtNgRefclockState',
                                            1)),
                  ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB',
                                            'mbgLtNgRefclockLeapSecondDate',
                                            1))])

        Parameters
        ----------
        oid_list : list
            List of high-level MIB Object OIDs. See `Specifying MIB Objects`_ for
            more info

        .. _Specifying MIB Objects:
            http://snmplabs.com/pysnmp/docs/pysnmp-hlapi-tutorial.html#specifying-mib-object

        """
        datagram = getCmd(self.snmp_engine,
                          CommunityData('public', mpModel=0),  # SNMPv1
                          self.udp_transport,
                          ContextData(),
                          *oid_list)

        datagram.addCallback(self._success).addErrback(self._failure)

        return datagram
