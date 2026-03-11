.. _snmp:

=========================================
Simple Network Management Protocol (SNMP)
=========================================

SOCS supports monitoring of networked devices via the Simple Network Management
Protocol (SNMP). SNMP is a standard protocol for collecting and organizing
information about devices on the network.

SNMP support is provided through the python module `pysnmp`_. pysnmp supports
twisted as an I/O framework, which integrates nicely with OCS/SOCS. SOCS makes this
twisted interface for SNMP available via the SNMPTwister class.

.. _pysnmp: http://snmplabs.com/pysnmp/contents.html

MIB to Python Conversion
------------------------
For developers adding a new SNMP monitoring OCS Agent, you may need to convert
a MIB file to python. This can be done with mibdump.py, a conversion script
provided by pysmi. Other useful (linux) packages for debugging include smitools
and snmp.

An example which converted the MBG-SNMP-LTNG-MIB .mib file::

    $ mibdump.py --mib-source . --mib-source /usr/share/snmp/mibs/ MBG-SNMP-LTNG-MIB
    Source MIB repositories: ., /usr/share/snmp/mibs/
    Borrow missing/failed MIBs from: http://mibs.snmplabs.com/pysnmp/notexts/@mib@
    Existing/compiled MIB locations: pysnmp.smi.mibs, pysnmp_mibs
    Compiled MIBs destination directory: /home/bjk49/.pysnmp/mibs
    MIBs excluded from code generation: INET-ADDRESS-MIB, PYSNMP-USM-MIB, RFC-1212, RFC-1215, RFC1065-SMI, RFC1155-SMI, RFC1158-MIB, RFC1213-MIB, SNMP-FRAMEWORK-MIB, SNMP-TARGET-MIB, SNMPv2-CONF, SNMPv2-SMI, SNMPv2-TC, SNMPv2-TM, TRANSPORT-ADDRESS-MIB
    MIBs to compile: MBG-SNMP-LTNG-MIB
    Destination format: pysnmp
    Parser grammar cache directory: not used
    Also compile all relevant MIBs: yes
    Rebuild MIBs regardless of age: no
    Dry run mode: no
    Create/update MIBs: yes
    Byte-compile Python modules: yes (optimization level no)
    Ignore compilation errors: no
    Generate OID->MIB index: no
    Generate texts in MIBs: no
    Keep original texts layout: no
    Try various file names while searching for MIB module: yes
    Created/updated MIBs: MBG-SNMP-LTNG-MIB, MBG-SNMP-ROOT-MIB, SNMPv2-MIB
    Pre-compiled MIBs borrowed:
    Up to date MIBs: SNMPv2-CONF, SNMPv2-SMI, SNMPv2-TC
    Missing source MIBs:
    Ignored MIBs:
    Failed MIBs:

.. note::
    There can be several "gotchas" during the conversion process, mostly to do
    with the naming of the .mib files and location of where they can be found. This
    example specifies the source locations manually. The ``--debug all`` flag can
    be useful in debugging conversion problems.

Examples
--------
A standalone example of using ``SNMPTwister`` to interact with a device::

    from twisted.internet import reactor
    from twisted.internet.defer import inlineCallbacks
    from socs.snmp import SNMPTwister

    # Setup communication with M1000
    snmp = SNMPTwister('10.10.10.186', 161)

    # Define OIDs to query
    get_list = [('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1),
                ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 1),
                ('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 2)]

    @inlineCallbacks
    def query_snmp():
        x = yield snmp.get(get_list)
        print(x)
        reactor.stop()

    # Call query_snmp within the reactor
    reactor.callWhenRunning(query_snmp)
    reactor.run()

This will return something like the following::

    $ python3 snmp_twister_test.py
    [ObjectType(ObjectIdentity(<ObjectName value object, tagSet <TagSet object, tags 0:0:6>, payload [1.3.6.1.4.1.5597.30.0.1.2.1.4.1]>), <Integer32 value object, tagSet <TagSet object, tags 0:0:2>, subtypeSpec <ConstraintsIntersection object, consts <ValueRangeConstraint object, consts -2147483648, 2147483647>, <ConstraintsUnion object, consts <SingleValueConstraint object, consts 0, 1, 2>>>, namedValues <NamedValues object, enums notAvailable=0, synchronized=1, notSynchronized=2>, payload [notSynchronized]>), ObjectType(ObjectIdentity(<ObjectName value object, tagSet <TagSet object, tags 0:0:6>, payload [1.3.6.1.4.1.5597...30.0.5.0.2.1.2.1]>), <Integer32 value object, tagSet <TagSet object, tags 0:0:2>, subtypeSpec <ConstraintsIntersection object, consts <ValueRangeConstraint object, consts -2147483648, 2147483647>, <ConstraintsUnion object, consts <SingleValueConstraint object, consts 0, 1, 2>>>, namedValues <NamedValues object, enums notAvailable=0, down=1, up=2>, payload [up]>), ObjectType(ObjectIdentity(<ObjectName value object, tagSet <TagSet object, tags 0:0:6>, payload [1.3.6.1.4.1.5597...30.0.5.0.2.1.2.2]>), <Integer32 value object, tagSet <TagSet object, tags 0:0:2>, subtypeSpec <ConstraintsIntersection object, consts <ValueRangeConstraint object, consts -2147483648, 2147483647>, <ConstraintsUnion object, consts <SingleValueConstraint object, consts 0, 1, 2>>>, namedValues <NamedValues object, enums notAvailable=0, down=1, up=2>, payload [up]>)]

See existing SNMP using agents, such as the Meinberg M1000 Agent for more
examples.

API
---

If you are developing an SNMP monitoring agent, the SNMP + twisted
interface is available for use and detailed here:

.. autoclass:: socs.snmp.SNMPTwister
    :members:
    :noindex:
