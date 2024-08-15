#
# PySNMP MIB module MBG-SYNCBOX-N2X-MIB (https://www.pysnmp.com/pysmi)
# ASN.1 source file://./MBG-SYNCBOX-N2X-MIB.mib
# Produced by pysmi-1.1.13 at Fri Oct 27 11:50:07 2023
# On host HAWKING platform Linux version 5.15.90.1-microsoft-standard-WSL2 by user davidvng
# Using Python version 3.8.8 (default, Apr 13 2021, 19:58:26)
#

Integer, ObjectIdentifier, OctetString = mibBuilder.importSymbols("ASN1", "Integer", "ObjectIdentifier", "OctetString")
NamedValues, = mibBuilder.importSymbols("ASN1-ENUMERATION", "NamedValues")
ValueSizeConstraint, ConstraintsIntersection, ValueRangeConstraint, SingleValueConstraint, ConstraintsUnion = mibBuilder.importSymbols("ASN1-REFINEMENT", "ValueSizeConstraint", "ConstraintsIntersection", "ValueRangeConstraint", "SingleValueConstraint", "ConstraintsUnion")
mbgSnmpRoot, = mibBuilder.importSymbols("MBG-SNMP-ROOT-MIB", "mbgSnmpRoot")
NotificationGroup, ModuleCompliance, ObjectGroup = mibBuilder.importSymbols("SNMPv2-CONF", "NotificationGroup", "ModuleCompliance", "ObjectGroup")
NotificationType, Integer32, MibScalar, MibTable, MibTableRow, MibTableColumn, TimeTicks, ObjectIdentity, iso, ModuleIdentity, Counter64, Unsigned32, Bits, Gauge32, Counter32, IpAddress, MibIdentifier = mibBuilder.importSymbols("SNMPv2-SMI", "NotificationType", "Integer32", "MibScalar", "MibTable", "MibTableRow", "MibTableColumn", "TimeTicks", "ObjectIdentity", "iso", "ModuleIdentity", "Counter64", "Unsigned32", "Bits", "Gauge32", "Counter32", "IpAddress", "MibIdentifier")
TextualConvention, DisplayString = mibBuilder.importSymbols("SNMPv2-TC", "TextualConvention", "DisplayString")
mbgSyncboxN2X = ModuleIdentity((1, 3, 6, 1, 4, 1, 5597, 40))
mbgSyncboxN2X.setRevisions(('2013-09-03 00:00',))
if mibBuilder.loadTexts:
    mbgSyncboxN2X.setLastUpdated('201309030000Z')
if mibBuilder.loadTexts:
    mbgSyncboxN2X.setOrganization('www.meinberg.de')
mbgSyncboxN2XGeneral = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 0))
mbgSyncboxN2XSerialNumber = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 0, 1), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XSerialNumber.setStatus('current')
mbgSyncboxN2XFirmwareRevision = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 0, 2), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XFirmwareRevision.setStatus('current')
mbgSyncboxN2XSystemTime = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 0, 3), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XSystemTime.setStatus('current')
mbgSyncboxN2XCurrentRefSource = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 0, 4), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XCurrentRefSource.setStatus('current')
mbgSyncboxN2XNetworkTimeProtocol = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 1))
mbgSyncboxN2XNtpSyncStatus = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 1, 1), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpSyncStatus.setStatus('current')
mbgSyncboxN2XNtpSystemPeer = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 1, 2), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpSystemPeer.setStatus('current')
mbgSyncboxN2XNtpStratum = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 1, 3), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpStratum.setStatus('current')
mbgSyncboxN2XNtpRefSourceTable = MibTable((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4), )
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceTable.setStatus('current')
mbgSyncboxN2XNtpRefSourceTableEntry = MibTableRow((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1), ).setIndexNames((0, "MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceIndex"))
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceTableEntry.setStatus('current')
mbgSyncboxN2XNtpRefSourceIndex = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 1), Unsigned32().subtype(subtypeSpec=ValueRangeConstraint(0, 6)))
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceIndex.setStatus('current')
mbgSyncboxN2XNtpRefSourceHostname = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 2), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceHostname.setStatus('current')
mbgSyncboxN2XNtpRefSourceStratum = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 3), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceStratum.setStatus('current')
mbgSyncboxN2XNtpRefSourceReferenceID = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 4), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceReferenceID.setStatus('current')
mbgSyncboxN2XNtpRefSourceReach = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 5), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceReach.setStatus('current')
mbgSyncboxN2XNtpRefSourceCurrPoll = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 6), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceCurrPoll.setStatus('current')
mbgSyncboxN2XNtpRefSourceMinPoll = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 7), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceMinPoll.setStatus('current')
mbgSyncboxN2XNtpRefSourceMaxPoll = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 8), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceMaxPoll.setStatus('current')
mbgSyncboxN2XNtpRefSourceConfigOptions = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 9), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceConfigOptions.setStatus('current')
mbgSyncboxN2XNtpRefSourcePathDelay = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 10), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourcePathDelay.setStatus('current')
mbgSyncboxN2XNtpRefSourceOffset = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 11), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceOffset.setStatus('current')
mbgSyncboxN2XNtpRefSourceJitter = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 1, 4, 1, 12), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XNtpRefSourceJitter.setStatus('current')
mbgSyncboxN2XPrecisionTimeProtocol = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 2))
mbgSyncboxN2XPtpProfile = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 1), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1, 2))).clone(namedValues=NamedValues(("none", 0), ("power", 1), ("telecom", 2)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpProfile.setStatus('current')
mbgSyncboxN2XPtpNwProt = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 2), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1, 2, 3, 4, 5, 6))).clone(namedValues=NamedValues(("unknown", 0), ("ipv4", 1), ("ipv6", 2), ("ieee802-3", 3), ("deviceNet", 4), ("controlNet", 5), ("profiNet", 6)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpNwProt.setStatus('current')
mbgSyncboxN2XPtpPortState = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 3), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1, 2, 3, 4, 5, 6, 7, 8, 9))).clone(namedValues=NamedValues(("uninitialized", 0), ("initializing", 1), ("faulty", 2), ("disabled", 3), ("listening", 4), ("preMaster", 5), ("master", 6), ("passive", 7), ("uncalibrated", 8), ("slave", 9)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpPortState.setStatus('current')
mbgSyncboxN2XPtpDelayMechanism = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 4), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1))).clone(namedValues=NamedValues(("e2e", 0), ("p2p", 1)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpDelayMechanism.setStatus('current')
mbgSyncboxN2XPtpDelayRequestInterval = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 5), Integer32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpDelayRequestInterval.setStatus('current')
mbgSyncboxN2XPtpTimescale = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 6), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1))).clone(namedValues=NamedValues(("tai", 0), ("arb", 1)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpTimescale.setStatus('current')
mbgSyncboxN2XPtpUTCOffset = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 7), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpUTCOffset.setStatus('current')
mbgSyncboxN2XPtpLeapSecondAnnounced = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 8), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpLeapSecondAnnounced.setStatus('current')
mbgSyncboxN2XPtpGrandmasterClockID = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 9), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterClockID.setStatus('current')
mbgSyncboxN2XPtpGrandmasterTimesource = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 10), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(16, 32, 48, 64, 80, 96, 144, 160))).clone(namedValues=NamedValues(("atomicClock", 16), ("gps", 32), ("terrestrialRadio", 48), ("ptp", 64), ("ntp", 80), ("handSet", 96), ("other", 144), ("internalOscillator", 160)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterTimesource.setStatus('current')
mbgSyncboxN2XPtpGrandmasterPriority1 = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 11), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterPriority1.setStatus('current')
mbgSyncboxN2XPtpGrandmasterClockClass = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 12), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterClockClass.setStatus('current')
mbgSyncboxN2XPtpGrandmasterClockAccuracy = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 13), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49))).clone(namedValues=NamedValues(("accurateToWithin25ns", 32), ("accurateToWithin100ns", 33), ("accurateToWithin250ns", 34), ("accurateToWithin1us", 35), ("accurateToWithin2Point5us", 36), ("accurateToWithin10us", 37), ("accurateToWithin25us", 38), ("accurateToWithin100us", 39), ("accurateToWithin250us", 40), ("accurateToWithin1ms", 41), ("accurateToWithin2Point5ms", 42), ("accurateToWithin10ms", 43), ("accurateToWithin25ms", 44), ("accurateToWithin100ms", 45), ("accurateToWithin250ms", 46), ("accurateToWithin1s", 47), ("accurateToWithin10s", 48), ("accurateToGreaterThan10s", 49)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterClockAccuracy.setStatus('current')
mbgSyncboxN2XPtpGrandmasterClockVariance = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 14), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterClockVariance.setStatus('current')
mbgSyncboxN2XPtpGrandmasterPriority2 = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 15), Unsigned32()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpGrandmasterPriority2.setStatus('current')
mbgSyncboxN2XPtpOffsetToGrandmaster = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 16), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpOffsetToGrandmaster.setStatus('current')
mbgSyncboxN2XPtpMeanPathDelay = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 2, 17), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XPtpMeanPathDelay.setStatus('current')
mbgSyncboxN2XOutputs = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 3))
mbgSyncboxN2XOutputsTable = MibTable((1, 3, 6, 1, 4, 1, 5597, 40, 3, 1), )
if mibBuilder.loadTexts:
    mbgSyncboxN2XOutputsTable.setStatus('current')
mbgSyncboxN2XOutputsTableEntry = MibTableRow((1, 3, 6, 1, 4, 1, 5597, 40, 3, 1, 1), ).setIndexNames((0, "MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XOutputIndex"))
if mibBuilder.loadTexts:
    mbgSyncboxN2XOutputsTableEntry.setStatus('current')
mbgSyncboxN2XOutputIndex = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 3, 1, 1, 1), Unsigned32().subtype(subtypeSpec=ValueRangeConstraint(0, 2)))
if mibBuilder.loadTexts:
    mbgSyncboxN2XOutputIndex.setStatus('current')
mbgSyncboxN2XOutputMode = MibTableColumn((1, 3, 6, 1, 4, 1, 5597, 40, 3, 1, 1, 2), Integer32().subtype(subtypeSpec=ConstraintsUnion(SingleValueConstraint(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16))).clone(namedValues=NamedValues(("idle", 0), ("timer", 1), ("singleShot", 2), ("cyclicPulse", 3), ("pulsePerSecond", 4), ("pulsePerMinute", 5), ("pulsePerHour", 6), ("emulatedDCF77", 7), ("positionOK", 8), ("timeSync", 9), ("allSync", 10), ("timecode", 11), ("timestring", 12), ("tenMHz", 13), ("emulatedDCF77M59", 14), ("synthesizer", 15), ("timeSlots", 16)))).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XOutputMode.setStatus('current')
mbgSyncboxN2XSerialString = MibScalar((1, 3, 6, 1, 4, 1, 5597, 40, 3, 2), DisplayString()).setMaxAccess("readonly")
if mibBuilder.loadTexts:
    mbgSyncboxN2XSerialString.setStatus('current')
mbgSyncboxN2XConformance = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 10))
mbgSyncboxN2XCompliances = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 10, 0))
mbgSyncboxN2XGroups = MibIdentifier((1, 3, 6, 1, 4, 1, 5597, 40, 10, 1))
mbgSyncboxN2XCompliance = ModuleCompliance((1, 3, 6, 1, 4, 1, 5597, 40, 10, 0, 0)).setObjects(("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XObjectsGroup"))

if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):
    mbgSyncboxN2XCompliance = mbgSyncboxN2XCompliance.setStatus('current')
mbgSyncboxN2XObjectsGroup = ObjectGroup((1, 3, 6, 1, 4, 1, 5597, 40, 10, 1, 0)).setObjects(("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XSerialNumber"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XFirmwareRevision"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XSystemTime"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XCurrentRefSource"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpSyncStatus"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpSystemPeer"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpStratum"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceHostname"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceStratum"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceReferenceID"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceReach"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceCurrPoll"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceMinPoll"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceMaxPoll"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceConfigOptions"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourcePathDelay"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceOffset"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XNtpRefSourceJitter"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpProfile"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpNwProt"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpPortState"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpDelayMechanism"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpDelayRequestInterval"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpTimescale"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpUTCOffset"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpLeapSecondAnnounced"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterClockID"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterTimesource"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterPriority1"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterClockClass"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterClockAccuracy"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterClockVariance"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpGrandmasterPriority2"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpOffsetToGrandmaster"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XPtpMeanPathDelay"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XOutputMode"), ("MBG-SYNCBOX-N2X-MIB", "mbgSyncboxN2XSerialString"))
if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):
    mbgSyncboxN2XObjectsGroup = mbgSyncboxN2XObjectsGroup.setStatus('current')
mibBuilder.exportSymbols("MBG-SYNCBOX-N2X-MIB", mbgSyncboxN2XPtpPortState=mbgSyncboxN2XPtpPortState, mbgSyncboxN2XPtpGrandmasterClockAccuracy=mbgSyncboxN2XPtpGrandmasterClockAccuracy, mbgSyncboxN2XCompliances=mbgSyncboxN2XCompliances, mbgSyncboxN2XNtpSyncStatus=mbgSyncboxN2XNtpSyncStatus, mbgSyncboxN2XNtpRefSourceTable=mbgSyncboxN2XNtpRefSourceTable, mbgSyncboxN2XPtpGrandmasterClockVariance=mbgSyncboxN2XPtpGrandmasterClockVariance, mbgSyncboxN2XNtpRefSourceCurrPoll=mbgSyncboxN2XNtpRefSourceCurrPoll, mbgSyncboxN2XNtpRefSourceReach=mbgSyncboxN2XNtpRefSourceReach, mbgSyncboxN2XNtpRefSourceJitter=mbgSyncboxN2XNtpRefSourceJitter, mbgSyncboxN2XSerialString=mbgSyncboxN2XSerialString, mbgSyncboxN2XNtpRefSourceMinPoll=mbgSyncboxN2XNtpRefSourceMinPoll, PYSNMP_MODULE_ID=mbgSyncboxN2X, mbgSyncboxN2XNtpRefSourceReferenceID=mbgSyncboxN2XNtpRefSourceReferenceID, mbgSyncboxN2XNtpRefSourceTableEntry=mbgSyncboxN2XNtpRefSourceTableEntry, mbgSyncboxN2XPtpOffsetToGrandmaster=mbgSyncboxN2XPtpOffsetToGrandmaster, mbgSyncboxN2XSystemTime=mbgSyncboxN2XSystemTime, mbgSyncboxN2XNtpRefSourceStratum=mbgSyncboxN2XNtpRefSourceStratum, mbgSyncboxN2XOutputsTableEntry=mbgSyncboxN2XOutputsTableEntry, mbgSyncboxN2XOutputMode=mbgSyncboxN2XOutputMode, mbgSyncboxN2XOutputIndex=mbgSyncboxN2XOutputIndex, mbgSyncboxN2XObjectsGroup=mbgSyncboxN2XObjectsGroup, mbgSyncboxN2XNtpRefSourceIndex=mbgSyncboxN2XNtpRefSourceIndex, mbgSyncboxN2XFirmwareRevision=mbgSyncboxN2XFirmwareRevision, mbgSyncboxN2XPtpGrandmasterPriority2=mbgSyncboxN2XPtpGrandmasterPriority2, mbgSyncboxN2XPtpGrandmasterClockClass=mbgSyncboxN2XPtpGrandmasterClockClass, mbgSyncboxN2XNtpRefSourceHostname=mbgSyncboxN2XNtpRefSourceHostname, mbgSyncboxN2XPrecisionTimeProtocol=mbgSyncboxN2XPrecisionTimeProtocol, mbgSyncboxN2XNtpSystemPeer=mbgSyncboxN2XNtpSystemPeer, mbgSyncboxN2X=mbgSyncboxN2X, mbgSyncboxN2XPtpMeanPathDelay=mbgSyncboxN2XPtpMeanPathDelay, mbgSyncboxN2XGroups=mbgSyncboxN2XGroups, mbgSyncboxN2XConformance=mbgSyncboxN2XConformance, mbgSyncboxN2XNtpRefSourceConfigOptions=mbgSyncboxN2XNtpRefSourceConfigOptions, mbgSyncboxN2XNtpRefSourceMaxPoll=mbgSyncboxN2XNtpRefSourceMaxPoll, mbgSyncboxN2XPtpGrandmasterClockID=mbgSyncboxN2XPtpGrandmasterClockID, mbgSyncboxN2XOutputs=mbgSyncboxN2XOutputs, mbgSyncboxN2XPtpDelayRequestInterval=mbgSyncboxN2XPtpDelayRequestInterval, mbgSyncboxN2XNtpRefSourcePathDelay=mbgSyncboxN2XNtpRefSourcePathDelay, mbgSyncboxN2XGeneral=mbgSyncboxN2XGeneral, mbgSyncboxN2XNtpRefSourceOffset=mbgSyncboxN2XNtpRefSourceOffset, mbgSyncboxN2XPtpGrandmasterTimesource=mbgSyncboxN2XPtpGrandmasterTimesource, mbgSyncboxN2XPtpGrandmasterPriority1=mbgSyncboxN2XPtpGrandmasterPriority1, mbgSyncboxN2XPtpDelayMechanism=mbgSyncboxN2XPtpDelayMechanism, mbgSyncboxN2XNetworkTimeProtocol=mbgSyncboxN2XNetworkTimeProtocol, mbgSyncboxN2XSerialNumber=mbgSyncboxN2XSerialNumber, mbgSyncboxN2XCompliance=mbgSyncboxN2XCompliance, mbgSyncboxN2XOutputsTable=mbgSyncboxN2XOutputsTable, mbgSyncboxN2XPtpNwProt=mbgSyncboxN2XPtpNwProt, mbgSyncboxN2XPtpUTCOffset=mbgSyncboxN2XPtpUTCOffset, mbgSyncboxN2XNtpStratum=mbgSyncboxN2XNtpStratum, mbgSyncboxN2XPtpLeapSecondAnnounced=mbgSyncboxN2XPtpLeapSecondAnnounced, mbgSyncboxN2XPtpTimescale=mbgSyncboxN2XPtpTimescale, mbgSyncboxN2XPtpProfile=mbgSyncboxN2XPtpProfile, mbgSyncboxN2XCurrentRefSource=mbgSyncboxN2XCurrentRefSource)
