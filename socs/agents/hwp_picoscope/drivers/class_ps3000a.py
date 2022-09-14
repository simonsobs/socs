'''
Copyright © 2018-2019 Pico Technology Ltd.

Permission to use, copy, modify, and/or distribute this software for any purpose with or without fee is hereby granted, provided that the above copyright notice and this permission notice appear in all copies.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
'''

import numpy as np
import time
import ctypes
from picosdk.ps3000a import ps3000a as ps
from picosdk.functions import adc2mV, assert_pico_ok, splitMSODataFast


class ps3000a():
    def __init__(self, sizeofbuffer, samplerate):
        self.status = {}
        self.chandle = ctypes.c_int16()
        self.interval = int(1. / samplerate * 1e9)  # unit ns

        # Size of capture
        self.sizeOfOneBuffer = sizeofbuffer
        self.numBuffersToCapture = 1
        self.totalSamples = self.sizeOfOneBuffer * self.numBuffersToCapture

        print('sample points: {}, sampling rate: {} (MHz), length: {} (sec)'.format(self.totalSamples, samplerate * 1e-6, self.totalSamples * self.interval * 1e-9))

        # Opens the device/s
        self.status["openunit"] = ps.ps3000aOpenUnit(ctypes.byref(self.chandle), None)

        self.info = {}
        self.info['sample_points'] = self.totalSamples
        self.info['sampling_rate_Hz'] = samplerate
        self.info['length_sec'] = self.totalSamples * self.interval * 1e-9

        try:
            assert_pico_ok(self.status["openunit"])
        except BaseException:

            # powerstate becomes the status number of openunit
            powerstate = self.status["openunit"]

            # If powerstate is the same as 282 then it will run this if statement
            if powerstate == 282:
                # Changes the power input to "PICO_POWER_SUPPLY_NOT_CONNECTED"
                self.status["ChangePowerSource"] = ps.ps3000aChangePowerSource(self.chandle, 282)
            # If the powerstate is the same as 286 then it will run this if statement
            elif powerstate == 286:
                # Changes the power input to "PICO_USB3_0_DEVICE_NON_USB3_0_PORT"
                self.status["ChangePowerSource"] = ps.ps3000aChangePowerSource(self.chandle, 286)
            else:
                raise
            assert_pico_ok(self.status["ChangePowerSource"])

    def close(self):
        # Closes the unit
        # Handle = chandle
        self.status["close"] = ps.ps3000aCloseUnit(self.chandle)
        assert_pico_ok(self.status["close"])

        '''
        ##### Signal Generator
        ### wavetype
        PS3000A_SINE sine wave
        PS3000A_SQUARE square wave
        PS3000A_TRIANGLE triangle wave
        PS3000A_DC_VOLTAGE DC voltage
        The following waveTypes apply to B and MSO models only.
        PS3000A_RAMP_UP rising sawtooth
        PS3000A_RAMP_DOWN falling sawtooth
        PS3000A_SINC sin (x)/x
        PS3000A_GAUSSIAN Gaussian
        PS3000A_HALF_SINE

        ###sweep type
        PS3000A_UP
        PS3000A_DOWN
        PS3000A_UPDOWN
        PS3000A_DOWNUP

        ###
        increment: the amount of frequency increase or decrease in sweep mode
        dwell time: the time for which the sweep stays at each frequency, in seconds
        '''

    def SigGenSingle(self, frequency, ptp=2000000):
        wavetype = ctypes.c_int16(0)
        sweepType = ctypes.c_int32(0)
        triggertype = ctypes.c_int32(0)
        triggerSource = ctypes.c_int32(0)

        offsetVoltage = 0
        pkToPk = ptp  # (uV)
        print('Drive frequency: {} (Hz), PKtoPK: {} (V)'.format(frequency, pkToPk * 1e-6))
        self.info['Drive_frequency_Hz'] = frequency
        self.info['PKtoPk'] = pkToPk * 1e-6

        start_frequency = frequency  # Hz
        stop_frequency = frequency  # Hz
        increment = 0
        dwelltime = 1

        self.status["SetSigGenBuiltIn"] = ps.ps3000aSetSigGenBuiltIn(
            self.chandle, offsetVoltage, pkToPk,
            wavetype, start_frequency, stop_frequency, increment, dwelltime, sweepType,
            0,  # operation
            0,  # shots
            0,  # sweeps
            triggertype,
            triggerSource,
            1,  # extInThreshold
        )
        assert_pico_ok(self.status["SetSigGenBuiltIn"])

    def SigGenSweep(self, start_frequency=100e3, stop_frequency=300e3, increment=5e2, dwelltime=1e-3):
        wavetype = ctypes.c_int16(0)
        sweepType = ctypes.c_int32(0)
        triggertype = ctypes.c_int32(0)
        triggerSource = ctypes.c_int32(0)

        offsetVoltage = 0
        pkToPk = 2000000  # (uV)

        self.status["SetSigGenBuiltIn"] = ps.ps3000aSetSigGenBuiltIn(
            self.chandle, offsetVoltage, pkToPk,
            wavetype, start_frequency, stop_frequency, increment, dwelltime, sweepType,
            0,  # operation
            0,  # shots
            0,  # sweeps
            triggertype,
            triggerSource,
            1,  # extInThreshold
        )
        assert_pico_ok(self.status["SetSigGenBuiltIn"])

    def SetScope(self):
        enabled = 1
        disabled = 0  # noqa: F841
        analogue_offset = 0.0

        # Set up channel A
        # handle = chandle
        # channel = PS3000A_CHANNEL_A = 0
        # enabled = 1
        # coupling type = PS3000A_DC = 1
        # range = PS3000A_2V = 7
        # analogue offset = 0 V
        self.channel_range = ps.PS3000A_RANGE['PS3000A_2V']

        self.status["setChA"] = ps.ps3000aSetChannel(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_A'],
            enabled,
            ps.PS3000A_COUPLING['PS3000A_DC'],
            self.channel_range,
            analogue_offset
        )
        assert_pico_ok(self.status["setChA"])

    def SetScopeAll(self):
        enabled = 1
        disabled = 0  # noqa: F841
        analogue_offset = 0.0

        # Set up channel A
        # handle = chandle
        # channel = PS3000A_CHANNEL_A = 0
        # enabled = 1
        # coupling type = PS3000A_DC = 1
        # range = PS3000A_2V = 7
        # analogue offset = 0 V
        self.channel_range = ps.PS3000A_RANGE['PS3000A_2V']

        for ch in ['A', 'B', 'C', 'D']:
            self.status['setCh' + ch] = ps.ps3000aSetChannel(
                self.chandle,
                ps.PS3000A_CHANNEL['PS3000A_CHANNEL_' + ch],
                enabled,
                ps.PS3000A_COUPLING['PS3000A_DC'],
                self.channel_range,
                analogue_offset
            )
            assert_pico_ok(self.status['setCh' + ch])

    def SetBuffer(self):
        # Create buffers ready for assigning pointers for data collection
        self.bufferAMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)
        self.bufferBMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)

        memory_segment = 0

        # Set data buffer location for data collection from channel A
        # handle = chandle
        # source = PS3000A_CHANNEL_A = 0
        # pointer to buffer max = ctypes.byref(bufferAMax)
        # pointer to buffer min = ctypes.byref(bufferAMin)
        # buffer length = maxSamples
        # segment index = 0
        # ratio mode = PS3000A_RATIO_MODE_NONE = 0
        self.status["setDataBuffersA"] = ps.ps3000aSetDataBuffers(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_A'],
            self.bufferAMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            None,
            self.sizeOfOneBuffer,
            memory_segment,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        )
        assert_pico_ok(self.status["setDataBuffersA"])

    def SetBufferAll(self):
        # Create buffers ready for assigning pointers for data collection
        self.bufferAMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)
        self.bufferBMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)
        self.bufferCMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)
        self.bufferDMax = np.zeros(shape=self.sizeOfOneBuffer, dtype=np.int16)

        memory_segment = 0

        # Set data buffer location for data collection from channel A
        # handle = chandle
        # source = PS3000A_CHANNEL_A = 0
        # pointer to buffer max = ctypes.byref(bufferAMax)
        # pointer to buffer min = ctypes.byref(bufferAMin)
        # buffer length = maxSamples
        # segment index = 0
        # ratio mode = PS3000A_RATIO_MODE_NONE = 0

        self.status["setDataBuffersA"] = ps.ps3000aSetDataBuffers(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_A'],
            self.bufferAMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            None,
            self.sizeOfOneBuffer,
            memory_segment,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        )
        assert_pico_ok(self.status["setDataBuffersA"])

        self.status["setDataBuffersB"] = ps.ps3000aSetDataBuffers(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_B'],
            self.bufferBMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            None,
            self.sizeOfOneBuffer,
            memory_segment,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        )
        assert_pico_ok(self.status["setDataBuffersB"])

        self.status["setDataBuffersC"] = ps.ps3000aSetDataBuffers(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_C'],
            self.bufferCMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            None,
            self.sizeOfOneBuffer,
            memory_segment,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        )
        assert_pico_ok(self.status["setDataBuffersC"])

        self.status["setDataBuffersD"] = ps.ps3000aSetDataBuffers(
            self.chandle,
            ps.PS3000A_CHANNEL['PS3000A_CHANNEL_D'],
            self.bufferDMax.ctypes.data_as(ctypes.POINTER(ctypes.c_int16)),
            None,
            self.sizeOfOneBuffer,
            memory_segment,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE']
        )
        assert_pico_ok(self.status["setDataBuffersD"])

    def Stream(self):
        # Begin streaming mode:
        sampleInterval = ctypes.c_int32(500)
        # print(sampleInterval.value)
        sampleUnits = ps.PS3000A_TIME_UNITS['PS3000A_NS']  # PS3000A_US, PS3000A_NS
        # We are not triggering:
        maxPreTriggerSamples = 0
        autoStopOn = 1
        # No downsampling:
        downsampleRatio = 1
        self.status["runStreaming"] = ps.ps3000aRunStreaming(
            self.chandle,
            ctypes.byref(sampleInterval),
            sampleUnits,
            maxPreTriggerSamples,
            self.totalSamples,
            autoStopOn,
            downsampleRatio,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE'],
            self.sizeOfOneBuffer
        )
        assert_pico_ok(self.status["runStreaming"])

        actualSampleInterval = sampleInterval.value
        # print(sampleInterval.value)
        self.actualSampleIntervalNs = actualSampleInterval * 1000

        print("Capturing at sample interval %s ns" % self.actualSampleIntervalNs)

        # We need a big buffer, not registered with the driver, to keep our complete capture in.
        self.bufferCompleteA = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteB = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteC = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteD = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.nextSample = 0
        self.autoStopOuter = False
        self.wasCalledBack = False
        # Convert the python function into a C function pointer.
        cFuncPtr = ps.StreamingReadyType(self._streaming_callback)

        # Fetch data from the driver in a loop,
        # copying it out of the registered buffers and into our complete one.

        while self.nextSample < self.totalSamples and not self.autoStopOuter:
            self.wasCalledBack = False
            self.status["getStreamingLastestValues"] = ps.ps3000aGetStreamingLatestValues(
                self.chandle,
                cFuncPtr,
                None
            )
            if not self.wasCalledBack:
                # If we weren't called back by the driver, this means no data is ready.
                # Sleep for a short while before trying
                # again.
                time.sleep(0.01)

        print("Done grabbing values.")
        print("Capturing interval %s sec" % (actualSampleInterval * 1000 * self.totalSamples / 1e12))

    def _streaming_callback(self, handle, noOfSamples, startIndex, overflow, triggerAt, triggered, autoStop, param):
        # global nextSample, autoStopOuter, wasCalledBack
        self.wasCalledBack = True
        destEnd = self.nextSample + noOfSamples
        sourceEnd = startIndex + noOfSamples
        self.bufferCompleteA[self.nextSample:destEnd] = self.bufferAMax[startIndex:sourceEnd]
        self.bufferCompleteB[self.nextSample:destEnd] = self.bufferBMax[startIndex:sourceEnd]
        self.bufferCompleteC[self.nextSample:destEnd] = self.bufferCMax[startIndex:sourceEnd]
        self.bufferCompleteD[self.nextSample:destEnd] = self.bufferDMax[startIndex:sourceEnd]
        self.nextSample += noOfSamples
        if autoStop:
            self.autoStopOuter = True

    def get_value(self):
        # Find maximum ADC count value
        # handle = chandle
        # pointer to value = ctypes.byref(maxADC)
        maxADC = ctypes.c_int16()
        self.status["maximumValue"] = ps.ps3000aMaximumValue(self.chandle, ctypes.byref(maxADC))
        assert_pico_ok(self.status["maximumValue"])

        # Convert ADC counts data to mV
        self.adc2mVChAMax = adc2mV(self.bufferCompleteA, self.channel_range, maxADC)
        self.adc2mVChBMax = adc2mV(self.bufferCompleteB, self.channel_range, maxADC)
        self.adc2mVChCMax = adc2mV(self.bufferCompleteC, self.channel_range, maxADC)
        self.adc2mVChDMax = adc2mV(self.bufferCompleteD, self.channel_range, maxADC)

        # Create time data
        self.t = np.linspace(0, (self.totalSamples) * self.actualSampleIntervalNs, self.totalSamples)

        return self.t, self.adc2mVChAMax, self.adc2mVChBMax, self.adc2mVChCMax, self.adc2mVChDMax

    def save_value(self, dir):
        np.savez(dir, t=self.t, A=self.adc2mVChAMax, B=self.adc2mVChBMax, C=self.adc2mVChCMax, D=self.adc2mVChDMax)

    # code-related-digital Input
    def set_digital_port(self):
        # Set up digital port
        # handle = chandle
        # channel = PS3000A_DIGITAL_PORT0 = 0x80
        # enabled = 1
        # logicLevel = 10000
        self.status["SetDigitalPort"] = ps.ps3000aSetDigitalPort(self.chandle, ps.PS3000A_DIGITAL_PORT["PS3000A_DIGITAL_PORT0"], 1, 10000)
        # self.status["SetDigitalPort"] = ps.ps3000aSetDigitalPort(self.chandle, ps.PS3000A_DIGITAL_PORT["PS3000A_DIGITAL_PORT1"], 1, 10000)
        assert_pico_ok(self.status["SetDigitalPort"])

    def set_digital_buffer(self):
        # Create buffers ready for assigning pointers for data collection
        self.bufferDPort0Max = (ctypes.c_int16 * self.totalSamples)()
        self.bufferDPort0Min = (ctypes.c_int16 * self.totalSamples)()

        # Set the data buffer location for data collection from PS3000A_DIGITAL_PORT0
        # handle = chandle
        # source = PS3000A_DIGITAL_PORT0 = 0x80
        # Buffer max = ctypes.byref(bufferDPort0Max)
        # Buffer min = ctypes.byref(bufferDPort0Min)
        # Buffer length = totalSamples
        # Segment index = 0
        # Ratio mode = PS3000A_RATIO_MODE_NONE = 0
        self.status["SetDataBuffers"] = ps.ps3000aSetDataBuffers(self.chandle,
                                                                 ps.PS3000A_DIGITAL_PORT["PS3000A_DIGITAL_PORT0"],  # digital_port0,
                                                                 ctypes.byref(self.bufferDPort0Max),
                                                                 ctypes.byref(self.bufferDPort0Min),
                                                                 self.totalSamples,
                                                                 0,
                                                                 0)
        assert_pico_ok(self.status["SetDataBuffers"])

    def get_digital_values_simple(self):
        # Obtain binary for Digital Port 0
        # The tuple returned contains the channels in order (D7, D6, D5, ... D0).
        cTotalSamples = ctypes.c_int32(self.totalSamples)
        self.bufferDPort0 = splitMSODataFast(cTotalSamples, self.bufferDPort0Max)

        return self.bufferDPort0

    def Stream_AD(self):
        # Begin streaming mode:
        sampleInterval = ctypes.c_int32(self.interval)
        # print(sampleInterval.value)
        sampleUnits = ps.PS3000A_TIME_UNITS['PS3000A_NS']  # PS3000A_US, PS3000A_NS
        # We are not triggering:
        maxPreTriggerSamples = 0
        autoStopOn = 1
        # No downsampling:
        downsampleRatio = 1
        self.status["runStreaming"] = ps.ps3000aRunStreaming(
            self.chandle,
            ctypes.byref(sampleInterval),
            sampleUnits,
            maxPreTriggerSamples,
            self.totalSamples,
            autoStopOn,
            downsampleRatio,
            ps.PS3000A_RATIO_MODE['PS3000A_RATIO_MODE_NONE'],
            self.sizeOfOneBuffer
        )
        assert_pico_ok(self.status["runStreaming"])

        actualSampleInterval = sampleInterval.value
        # print(sampleInterval.value)
        self.actualSampleIntervalNs = actualSampleInterval * 1000

        print("Capturing at sample interval %s ns" % self.actualSampleIntervalNs)

        # We need a big buffer, not registered with the driver, to keep our complete capture in.
        self.bufferCompleteA = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteB = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteC = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteD = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteDport0M = np.zeros(shape=self.totalSamples, dtype=np.int16)
        self.bufferCompleteDport0m = np.zeros(shape=self.totalSamples, dtype=np.int16)

        self.nextSample = 0
        self.autoStopOuter = False
        self.wasCalledBack = False
        # Convert the python function into a C function pointer.
        cFuncPtr = ps.StreamingReadyType(self._streaming_callback_AD)

        # Fetch data from the driver in a loop,
        # copying it out of the registered buffers and into our complete one.

        while self.nextSample < self.totalSamples and not self.autoStopOuter:
            self.wasCalledBack = False
            self.status["getStreamingLastestValues"] = ps.ps3000aGetStreamingLatestValues(
                self.chandle,
                cFuncPtr,
                None
            )
            if not self.wasCalledBack:
                # If we weren't called back by the driver, this means no data is ready.
                # Sleep for a short while before trying
                # again.
                time.sleep(0.01)

        print("Done grabbing values.")
        print("Capturing interval %s sec" % (actualSampleInterval * 1000 * self.totalSamples / 1e12))

    def _streaming_callback_AD(self, handle, noOfSamples, startIndex, overflow, triggerAt, triggered, autoStop, param):
        # global nextSample, autoStopOuter, wasCalledBack
        self.wasCalledBack = True
        destEnd = self.nextSample + noOfSamples
        sourceEnd = startIndex + noOfSamples
        self.bufferCompleteA[self.nextSample:destEnd] = self.bufferAMax[startIndex:sourceEnd]
        self.bufferCompleteB[self.nextSample:destEnd] = self.bufferBMax[startIndex:sourceEnd]
        self.bufferCompleteC[self.nextSample:destEnd] = self.bufferCMax[startIndex:sourceEnd]
        self.bufferCompleteD[self.nextSample:destEnd] = self.bufferDMax[startIndex:sourceEnd]
        self.bufferCompleteDport0M[self.nextSample:destEnd] = self.bufferDPort0Max[startIndex:sourceEnd]
        self.bufferCompleteDport0m[self.nextSample:destEnd] = self.bufferDPort0Min[startIndex:sourceEnd]
        self.nextSample += noOfSamples
        if autoStop:
            self.autoStopOuter = True
