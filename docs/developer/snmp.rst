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

.. note::

    These examples assume you're in the reactor context, i.e. running in an OCS
    Agent non-blocking task or process. This primarily means we don't start the
    reactor or any sort of runner ourselves.

Initializing an SNMPTwister::

    from socs.snmp import SNMPTwister

    snmp = SNMPTwister(address, port)

    get_list = [ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgRefclockState', 1)),
                ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 1)),
                ObjectType(ObjectIdentity('MBG-SNMP-LTNG-MIB', 'mbgLtNgSysPsStatus', 2))]

    result = yield snmp.get(get_list)

For standalone examples, see the `pysnmp`_ documentation.

API
---

If you are developing an SNMP monitoring agent, the SNMP + twisted
interface is available for use and detailed here:

.. autoclass:: socs.snmp.SNMPTwister
    :members:
