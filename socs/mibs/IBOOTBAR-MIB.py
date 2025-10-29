# SNMP MIB module (IBOOTBAR-MIB) expressed in pysnmp data model.
#
# This Python module is designed to be imported and executed by the
# pysnmp library.
#
# See https://www.pysnmp.com/pysnmp for further information.
#
# Notes
# -----
# ASN.1 source file://./IBOOTBAR-MIB.mib
# Produced by pysmi-1.5.9 at Tue Apr 22 14:30:23 2025
# On host login platform Linux version 5.15.0-136-generic by user ykyohei
# Using Python version 3.10.12 (main, Jul  5 2023, 18:54:27) [GCC 11.2.0]

if 'mibBuilder' not in globals():
    import sys

    sys.stderr.write(__doc__)
    sys.exit(1)

# Import base ASN.1 objects even if this MIB does not use it

(Integer,
 OctetString,
 ObjectIdentifier) = mibBuilder.importSymbols(
    "ASN1",
    "Integer",
    "OctetString",
    "ObjectIdentifier")

(NamedValues,) = mibBuilder.importSymbols(
    "ASN1-ENUMERATION",
    "NamedValues")
(ConstraintsIntersection,
 ConstraintsUnion,
 SingleValueConstraint,
 ValueRangeConstraint,
 ValueSizeConstraint) = mibBuilder.importSymbols(
    "ASN1-REFINEMENT",
    "ConstraintsIntersection",
    "ConstraintsUnion",
    "SingleValueConstraint",
    "ValueRangeConstraint",
    "ValueSizeConstraint")

# Import SMI symbols from the MIBs this MIB depends on

(ModuleCompliance,
 NotificationGroup) = mibBuilder.importSymbols(
    "SNMPv2-CONF",
    "ModuleCompliance",
    "NotificationGroup")

(Bits,
 Counter32,
 Counter64,
 Gauge32,
 Integer32,
 IpAddress,
 ModuleIdentity,
 MibIdentifier,
 NotificationType,
 ObjectIdentity,
 MibScalar,
 MibTable,
 MibTableRow,
 MibTableColumn,
 TimeTicks,
 Unsigned32,
 enterprises,
 iso) = mibBuilder.importSymbols(
    "SNMPv2-SMI",
    "Bits",
    "Counter32",
    "Counter64",
    "Gauge32",
    "Integer32",
    "IpAddress",
    "ModuleIdentity",
    "MibIdentifier",
    "NotificationType",
    "ObjectIdentity",
    "MibScalar",
    "MibTable",
    "MibTableRow",
    "MibTableColumn",
    "TimeTicks",
    "Unsigned32",
    "enterprises",
    "iso")

(DisplayString,
 PhysAddress,
 TextualConvention) = mibBuilder.importSymbols(
    "SNMPv2-TC",
    "DisplayString",
    "PhysAddress",
    "TextualConvention")


# MODULE-IDENTITY

dataprobe = ModuleIdentity(
    (1, 3, 6, 1, 4, 1, 1418)
)


# Types definitions


# TEXTUAL-CONVENTIONS



class TC1(TextualConvention, Integer32):
    status = "current"


# MIB Managed Objects in the order of their OIDs

_IBootBarAgent_ObjectIdentity = ObjectIdentity
iBootBarAgent = _IBootBarAgent_ObjectIdentity(
    (1, 3, 6, 1, 4, 1, 1418, 4)
)
_SystemSettings_ObjectIdentity = ObjectIdentity
systemSettings = _SystemSettings_ObjectIdentity(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1)
)
_DeviceName_Type = DisplayString
_DeviceName_Object = MibScalar
deviceName = _DeviceName_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 1),
    _DeviceName_Type()
)
deviceName.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    deviceName.setStatus("current")


class _IpMode_Type(Integer32):
    """Custom type ipMode based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1,
              2)
        )
    )
    namedValues = NamedValues(
        *(("static", 0),
          ("arp-ping", 1),
          ("dhcp", 2))
    )


_IpMode_Type.__name__ = "Integer32"
_IpMode_Object = MibScalar
ipMode = _IpMode_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 2),
    _IpMode_Type()
)
ipMode.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    ipMode.setStatus("current")


class _IpAddress_Type(DisplayString):
    """Custom type ipAddress based on DisplayString"""
    subtypeSpec = DisplayString.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueSizeConstraint(16, 16),
    )
    fixedLength = 16


_IpAddress_Type.__name__ = "DisplayString"
_IpAddress_Object = MibScalar
ipAddress = _IpAddress_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 3),
    _IpAddress_Type()
)
ipAddress.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    ipAddress.setStatus("current")


class _SubnetMask_Type(DisplayString):
    """Custom type subnetMask based on DisplayString"""
    subtypeSpec = DisplayString.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueSizeConstraint(16, 16),
    )
    fixedLength = 16


_SubnetMask_Type.__name__ = "DisplayString"
_SubnetMask_Object = MibScalar
subnetMask = _SubnetMask_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 4),
    _SubnetMask_Type()
)
subnetMask.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    subnetMask.setStatus("current")


class _Gateway_Type(DisplayString):
    """Custom type gateway based on DisplayString"""
    subtypeSpec = DisplayString.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueSizeConstraint(16, 16),
    )
    fixedLength = 16


_Gateway_Type.__name__ = "DisplayString"
_Gateway_Object = MibScalar
gateway = _Gateway_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 5),
    _Gateway_Type()
)
gateway.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    gateway.setStatus("current")


class _WebEnable_Type(Integer32):
    """Custom type webEnable based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("false", 0),
          ("true", 1))
    )


_WebEnable_Type.__name__ = "Integer32"
_WebEnable_Object = MibScalar
webEnable = _WebEnable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 6),
    _WebEnable_Type()
)
webEnable.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    webEnable.setStatus("current")


class _WebPort_Type(Integer32):
    """Custom type webPort based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueRangeConstraint(0, 65535),
    )


_WebPort_Type.__name__ = "Integer32"
_WebPort_Object = MibScalar
webPort = _WebPort_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 7),
    _WebPort_Type()
)
webPort.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    webPort.setStatus("current")


class _SslEnable_Type(Integer32):
    """Custom type sslEnable based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("false", 0),
          ("true", 1))
    )


_SslEnable_Type.__name__ = "Integer32"
_SslEnable_Object = MibScalar
sslEnable = _SslEnable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 8),
    _SslEnable_Type()
)
sslEnable.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    sslEnable.setStatus("current")


class _TelnetEnable_Type(Integer32):
    """Custom type telnetEnable based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("false", 0),
          ("true", 1))
    )


_TelnetEnable_Type.__name__ = "Integer32"
_TelnetEnable_Object = MibScalar
telnetEnable = _TelnetEnable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 9),
    _TelnetEnable_Type()
)
telnetEnable.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    telnetEnable.setStatus("current")


class _TelnetPort_Type(Integer32):
    """Custom type telnetPort based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueRangeConstraint(0, 65535),
    )


_TelnetPort_Type.__name__ = "Integer32"
_TelnetPort_Object = MibScalar
telnetPort = _TelnetPort_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 10),
    _TelnetPort_Type()
)
telnetPort.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    telnetPort.setStatus("current")


class _UpdateEnable_Type(Integer32):
    """Custom type updateEnable based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("false", 0),
          ("true", 1))
    )


_UpdateEnable_Type.__name__ = "Integer32"
_UpdateEnable_Object = MibScalar
updateEnable = _UpdateEnable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 11),
    _UpdateEnable_Type()
)
updateEnable.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    updateEnable.setStatus("current")
_CycleTime_Type = Integer32
_CycleTime_Object = MibScalar
cycleTime = _CycleTime_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 12),
    _CycleTime_Type()
)
cycleTime.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    cycleTime.setStatus("current")
_DelayTime_Type = Integer32
_DelayTime_Object = MibScalar
delayTime = _DelayTime_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 1, 13),
    _DelayTime_Type()
)
delayTime.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    delayTime.setStatus("current")
_SnmpManagerTable_Object = MibTable
snmpManagerTable = _SnmpManagerTable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 2)
)
if mibBuilder.loadTexts:
    snmpManagerTable.setStatus("current")
_SnmpManagerEntry_Object = MibTableRow
snmpManagerEntry = _SnmpManagerEntry_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 2, 1)
)
snmpManagerEntry.setIndexNames(
    (0, "IBOOTBAR-MIB", "snmpManagerIndex"),
)
if mibBuilder.loadTexts:
    snmpManagerEntry.setStatus("current")
_SnmpManagerIndex_Type = Integer32
_SnmpManagerIndex_Object = MibTableColumn
snmpManagerIndex = _SnmpManagerIndex_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 2, 1, 1),
    _SnmpManagerIndex_Type()
)
snmpManagerIndex.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    snmpManagerIndex.setStatus("current")


class _SnmpManagerIPAddress_Type(DisplayString):
    """Custom type snmpManagerIPAddress based on DisplayString"""
    subtypeSpec = DisplayString.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueSizeConstraint(16, 16),
    )
    fixedLength = 16


_SnmpManagerIPAddress_Type.__name__ = "DisplayString"
_SnmpManagerIPAddress_Object = MibTableColumn
snmpManagerIPAddress = _SnmpManagerIPAddress_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 2, 1, 2),
    _SnmpManagerIPAddress_Type()
)
snmpManagerIPAddress.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    snmpManagerIPAddress.setStatus("current")


class _SnmpManagerEnable_Type(Integer32):
    """Custom type snmpManagerEnable based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("false", 0),
          ("true", 1))
    )


_SnmpManagerEnable_Type.__name__ = "Integer32"
_SnmpManagerEnable_Object = MibTableColumn
snmpManagerEnable = _SnmpManagerEnable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 2, 1, 3),
    _SnmpManagerEnable_Type()
)
snmpManagerEnable.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    snmpManagerEnable.setStatus("current")
_OutletTable_Object = MibTable
outletTable = _OutletTable_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3)
)
if mibBuilder.loadTexts:
    outletTable.setStatus("current")
_OutletEntry_Object = MibTableRow
outletEntry = _OutletEntry_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1)
)
outletEntry.setIndexNames(
    (0, "IBOOTBAR-MIB", "outletIndex"),
)
if mibBuilder.loadTexts:
    outletEntry.setStatus("current")


class _OutletIndex_Type(Integer32):
    """Custom type outletIndex based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueRangeConstraint(0, 7),
    )


_OutletIndex_Type.__name__ = "Integer32"
_OutletIndex_Object = MibTableColumn
outletIndex = _OutletIndex_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1, 1),
    _OutletIndex_Type()
)
outletIndex.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    outletIndex.setStatus("current")


class _OutletName_Type(OctetString):
    """Custom type outletName based on OctetString"""
    subtypeSpec = OctetString.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        ValueSizeConstraint(20, 20),
    )
    fixedLength = 20


_OutletName_Type.__name__ = "OctetString"
_OutletName_Object = MibTableColumn
outletName = _OutletName_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1, 2),
    _OutletName_Type()
)
outletName.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    outletName.setStatus("current")


class _OutletStatus_Type(Integer32):
    """Custom type outletStatus based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1,
              2,
              3,
              4,
              5)
        )
    )
    namedValues = NamedValues(
        *(("off", 0),
          ("on", 1),
          ("reboot", 2),
          ("cycle", 3),
          ("onPending", 4),
          ("cyclePending", 5))
    )


_OutletStatus_Type.__name__ = "Integer32"
_OutletStatus_Object = MibTableColumn
outletStatus = _OutletStatus_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1, 3),
    _OutletStatus_Type()
)
outletStatus.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    outletStatus.setStatus("current")


class _OutletCommand_Type(Integer32):
    """Custom type outletCommand based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1,
              2)
        )
    )
    namedValues = NamedValues(
        *(("off", 0),
          ("on", 1),
          ("cycle", 2))
    )


_OutletCommand_Type.__name__ = "Integer32"
_OutletCommand_Object = MibTableColumn
outletCommand = _OutletCommand_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1, 4),
    _OutletCommand_Type()
)
outletCommand.setMaxAccess("read-write")
if mibBuilder.loadTexts:
    outletCommand.setStatus("current")


class _OutletAPStatus_Type(Integer32):
    """Custom type outletAPStatus based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("ok", 0),
          ("triggered", 1))
    )


_OutletAPStatus_Type.__name__ = "Integer32"
_OutletAPStatus_Object = MibTableColumn
outletAPStatus = _OutletAPStatus_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 3, 1, 5),
    _OutletAPStatus_Type()
)
outletAPStatus.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    outletAPStatus.setStatus("current")
_Info_ObjectIdentity = ObjectIdentity
info = _Info_ObjectIdentity(
    (1, 3, 6, 1, 4, 1, 1418, 4, 4)
)
_CurrentLC1_Type = Integer32
_CurrentLC1_Object = MibScalar
currentLC1 = _CurrentLC1_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 4, 1),
    _CurrentLC1_Type()
)
currentLC1.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    currentLC1.setStatus("current")
_CurrentLC2_Type = Integer32
_CurrentLC2_Object = MibScalar
currentLC2 = _CurrentLC2_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 4, 2),
    _CurrentLC2_Type()
)
currentLC2.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    currentLC2.setStatus("current")


class _NumberOfLineCords_Type(Integer32):
    """Custom type numberOfLineCords based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1)
        )
    )
    namedValues = NamedValues(
        *(("oneLineCord", 0),
          ("twoLineCords", 1))
    )


_NumberOfLineCords_Type.__name__ = "Integer32"
_NumberOfLineCords_Object = MibScalar
numberOfLineCords = _NumberOfLineCords_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 4, 3),
    _NumberOfLineCords_Type()
)
numberOfLineCords.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    numberOfLineCords.setStatus("current")


class _EmailStatus_Type(Integer32):
    """Custom type emailStatus based on Integer32"""
    subtypeSpec = Integer32.subtypeSpec
    subtypeSpec += ConstraintsUnion(
        SingleValueConstraint(
            *(0,
              1,
              2,
              3,
              4,
              5,
              6)
        )
    )
    namedValues = NamedValues(
        *(("emailSuccess", 0),
          ("emailTimeout", 1),
          ("emailInvalidResponse", 2),
          ("emailDNSFail", 3),
          ("emailAborted", 4),
          ("emailAuthFailed", 5),
          ("errorNotAvail", 6))
    )


_EmailStatus_Type.__name__ = "Integer32"
_EmailStatus_Object = MibScalar
emailStatus = _EmailStatus_Object(
    (1, 3, 6, 1, 4, 1, 1418, 4, 4, 4),
    _EmailStatus_Type()
)
emailStatus.setMaxAccess("read-only")
if mibBuilder.loadTexts:
    emailStatus.setStatus("current")

# Managed Objects groups


# Notification objects

outletChange = NotificationType(
    (1, 3, 6, 1, 4, 1, 1418, 4, 5)
)
outletChange.setObjects(
      *(("IBOOTBAR-MIB", "outletName"),
        ("IBOOTBAR-MIB", "outletStatus"))
)
if mibBuilder.loadTexts:
    outletChange.setStatus(
        "current"
    )

autoPingFailed = NotificationType(
    (1, 3, 6, 1, 4, 1, 1418, 4, 6)
)
autoPingFailed.setObjects(
    ("IBOOTBAR-MIB", "outletAPStatus")
)
if mibBuilder.loadTexts:
    autoPingFailed.setStatus(
        "current"
    )

currentAlarm = NotificationType(
    (1, 3, 6, 1, 4, 1, 1418, 4, 7)
)
currentAlarm.setObjects(
      *(("IBOOTBAR-MIB", "currentLC1"),
        ("IBOOTBAR-MIB", "currentLC2"))
)
if mibBuilder.loadTexts:
    currentAlarm.setStatus(
        "current"
    )

emailError = NotificationType(
    (1, 3, 6, 1, 4, 1, 1418, 4, 8)
)
emailError.setObjects(
    ("IBOOTBAR-MIB", "emailStatus")
)
if mibBuilder.loadTexts:
    emailError.setStatus(
        "current"
    )


# Notifications groups


# Agent capabilities


# Module compliance


# Export all MIB objects to the MIB builder

mibBuilder.exportSymbols(
    "IBOOTBAR-MIB",
    **{"TC1": TC1,
       "dataprobe": dataprobe,
       "iBootBarAgent": iBootBarAgent,
       "systemSettings": systemSettings,
       "deviceName": deviceName,
       "ipMode": ipMode,
       "ipAddress": ipAddress,
       "subnetMask": subnetMask,
       "gateway": gateway,
       "webEnable": webEnable,
       "webPort": webPort,
       "sslEnable": sslEnable,
       "telnetEnable": telnetEnable,
       "telnetPort": telnetPort,
       "updateEnable": updateEnable,
       "cycleTime": cycleTime,
       "delayTime": delayTime,
       "snmpManagerTable": snmpManagerTable,
       "snmpManagerEntry": snmpManagerEntry,
       "snmpManagerIndex": snmpManagerIndex,
       "snmpManagerIPAddress": snmpManagerIPAddress,
       "snmpManagerEnable": snmpManagerEnable,
       "outletTable": outletTable,
       "outletEntry": outletEntry,
       "outletIndex": outletIndex,
       "outletName": outletName,
       "outletStatus": outletStatus,
       "outletCommand": outletCommand,
       "outletAPStatus": outletAPStatus,
       "info": info,
       "currentLC1": currentLC1,
       "currentLC2": currentLC2,
       "numberOfLineCords": numberOfLineCords,
       "emailStatus": emailStatus,
       "outletChange": outletChange,
       "autoPingFailed": autoPingFailed,
       "currentAlarm": currentAlarm,
       "emailError": emailError}
)
