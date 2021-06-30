#!/usr/bin/env python3
# Lakeshore370.py

import sys
import serial
import time
import numpy as np

import traceback

# Lookup keys for command parameters.
autorange_key = {'0': 'off',
                 '1': 'on'}

mode_key = {'0': 'voltage',
            '1': 'current'}

mode_lock = {'voltage': '0',
             'current': '1'}

voltage_excitation_key = {1: 2.0e-6,
                          2: 6.32e-6,
                          3: 20.0e-6,
                          4: 63.2e-6,
                          5: 200.0e-6,
                          6: 632.0e-6,
                          7: 2.0e-3,
                          8: 6.32e-3,
                          9: 20.0e-3,
                          10: 63.2e-3,
                          11: 200.0e-3,
                          12: 632.0e-3}

current_excitation_key = {1: 1.0e-12,
                          2: 3.16e-12,
                          3: 10.0e-12,
                          4: 31.6e-12,
                          5: 100.0e-12,
                          6: 316.0e-12,
                          7: 1.0e-9,
                          8: 3.16e-9,
                          9: 10.0e-9,
                          10: 31.6e-9,
                          11: 100.0e-9,
                          12: 316.0e-9,
                          13: 1.0e-6,
                          14: 3.16e-6,
                          15: 10.0e-6,
                          16: 31.6e-6,
                          17: 100.0e-6,
                          18: 316.0e-6,
                          19: 1.0e-3,
                          20: 3.16e-3,
                          21: 10.0-3,
                          22: 31.6-3}

voltage_excitation_lock = {2.0e-6: 1,
                           6.32e-6: 2,
                           20.0e-6: 3,
                           63.2e-6: 4,
                           200.0e-6: 5,
                           632.0e-6: 6,
                           2.0e-3: 7,
                           6.32e-3: 8,
                           20.0e-3: 9,
                           63.2e-3: 10,
                           200.0e-3: 11,
                           632.0e-3: 12}

current_excitation_lock = {1.0e-12: 1,
                           3.16e-12: 2,
                           10.0e-12: 3,
                           31.6e-12: 4,
                           100.0e-12: 5,
                           316.0e-12: 6,
                           1.0e-9: 7,
                           3.16e-9: 8,
                           10.0e-9: 9,
                           31.6e-9: 10,
                           100.0e-9: 11,
                           316.0e-9: 12,
                           1.0e-6: 13,
                           3.16e-6: 14,
                           10.0e-6: 15,
                           31.6e-6: 16,
                           100.0e-6: 17,
                           316.0e-6: 18,
                           1.0e-3: 19,
                           3.16e-3: 20,
                           10.0-3: 21,
                           31.6-3: 22}

range_key = {1: 2.0e-3,
             2: 6.32e-3,
             3: 20.0e-3,
             4: 63.2e-3,
             5: 200e-3,
             6: 632e-3,
             7: 2.0,
             8: 6.32,
             9: 20.0,
             10: 63.2,
             11: 200,
             12: 632,
             13: 2e3,
             14: 6.32e3,
             15: 20.0e3,
             16: 63.2e3,
             17: 200e3,
             18: 632e3,
             19: 2e6,
             20: 6.32e6,
             21: 20.0e6,
             22: 63.2e6}

range_lock = {2.0e-3: 1,
              6.32e-3: 2,
              20.0e-3: 3,
              63.2e-3: 4,
              200e-3: 5,
              632e-3: 6,
              2.0: 7,
              6.32: 8,
              20.0: 9,
              63.2: 10,
              200: 11,
              632: 12,
              2e3: 13,
              6.32e3: 14,
              20.0e3: 15,
              63.2e3: 16,
              200e3: 17,
              632e3: 18,
              2e6: 19,
              6.32e6: 20,
              20.0e6: 21,
              63.2e6: 22}

units_key = {'1': 'kelvin',
             '2': 'ohms'}

units_lock = {'kelvin': '1',
              'ohms': '2'}

csshunt_key = {'0': 'on',
               '1': 'off'}

tempco_key = {'1': 'negative',
              '2': 'positive'}

tempco_lock = {'negative': '1',
               'positive': '2'}

format_key = {'3': "Ohm/K (linear)",
              '4': "log Ohm/K (linear)"}

format_lock = {"Ohm/K (linear)": '3',
               "log Ohm/K (linear)": '4'}

heater_range_key = {"0": "Off", "1": 31.6e-6, "2": 100e-6, "3": 316e-6,
                    "4": 1e-3, "5": 3.16e-3, "6": 10e-3, "7": 31.6e-3,
                    "8": 100e-3}
heater_range_lock = {v:k for k, v in heater_range_key.items()}
heater_range_lock["On"] = "1"

output_modes = {'1': 'Closed Loop', '2': 'Zone', '3': 'Open Loop', '4': 'Off'}
output_modes_lock = {v.lower():k for k, v in output_modes.items()}

analog_modes = {'0': 'Off', '1': 'Channel', '2': 'Manual', '3': 'Zone', '4': 'Still'}
analog_modes_lock = {v.lower():k for k, v in analog_modes.items()}

heater_display_key = { '1': 'current',
                '2': 'power'}
heater_display_lock = {v: k for k,v in heater_display_key.items()}


class LS370:
    """
        Lakeshore 370 class.

    Attributes:
        channels - list of channels, index corresponds to channel number with
                   index 0 corresponding to channel 1
    """

    _bytesize = serial.SEVENBITS
    _parity = serial.PARITY_ODD
    _stopbits = serial.STOPBITS_ONE

    def __init__(self, port, baudrate=9600, timeout=10, num_channels=16):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout

        print(self.baudrate)

        self.com = serial.Serial(self.port, self.baudrate, self._bytesize, self._parity, self._stopbits, self.timeout)
        self.num_channels = num_channels

        self.id = self.get_id()
        self.autoscan = self.get_autoscan()
        
        self.channels = []

        #unlike 372, 370 does not have dedicated control input channel; rather, only numbered channels 
        for i in range(1, num_channels + 1):
            c = Channel(self, i)
            self.channels.append(c)

        self.sample_heater = Heater(self)
        #self.still_heater = Heater(self, 2)

    def msg(self, message):
        """Send message to the Lakeshore 370 over RS-232.

        If we're asking for something from the Lakeshore (indicated by a ? in
        the message string), then we will attempt to ask twice before giving up
        due to potential communication timeouts.

        Parameters
        ----------
        message : str
            Message string as described in the Lakeshore 370 manual.

        Returns
        -------
        str
            Response string from the Lakeshore, if any. Else, an empty string.

        """
        msg_str = f'{message}\r\n'.encode()
        self.com.write(msg_str)
        resp = ''

        if '?' in message:
            resp = str(self.com.read_until(), 'utf-8').strip()

            # Try a few times, if we timeout, try again.
            try_count = 3
            while resp == '':
                if try_count == 0:
                    break
                
                print(f"Warning: Caught timeout waiting for response to {message}, waiting 1s and " \
                          "trying again {try_count} more time(s) before giving up")
                time.sleep(1)

                # retry comms
                self.com.write(msg_str)
                resp = str(self.com.read_until(), 'utf-8').strip()
                try_count -= 1

        time.sleep(0.1)  # No comms for 100ms after sending message (manual says 50ms)

        return resp

    def get_id(self):
        """Get the ID number of the Lakeshore unit."""
        return self.msg('*IDN?')

    def get_temp(self, unit='kelvin', chan=-1):
        """Get temperature from the Lakeshore.

        Args:
            unit (str): Unit to return reading for ('ohms' or 'kelvin')
            chan (int): Channel to query, -1 for currently active channel

        Returns:
            float: The reading from the lakeshore, either in ohms or kelvin.

        """
        if (chan == -1):
            resp = self.msg("SCAN?")
            c = int(resp.split(',')[0])
        else:
            c = chan

        channel = self.chan_num2channel(c)

        assert unit.lower() in ['ohms', 'kelvin']

        if unit == 'ohms':
            return float(channel.get_resistance_reading())
        if unit == 'kelvin':
            return float(channel.get_kelvin_reading())

    def get_autoscan(self):
        """Determine state of autoscan.

        :returns: state of autoscanner
        :rtype: bool
        """
        resp = self.msg('SCAN?')
        scan_state = bool(int(resp.split(',')[1]))
        self.autoscan = scan_state
        return scan_state

    def _set_autoscan(self, start=1, autoscan=0):
        """Set the autoscan state and start channel for scanning.

        :param start: Channel number to start scanning
        :type start: int
        :param autoscan: State of autoscan, 0 for off, 1 for on
        :type autoscan: int
        """
        assert autoscan in [0, 1]

        self.msg('SCAN {},{}'.format(start, autoscan))
        self.autoscan = bool(autoscan)

    def enable_autoscan(self):
        """Enable the autoscan feature of the Lakeshore 370.

        Will query active channel to pass already selected channel to SCAN
        command.
        """
        active_channel = self.get_active_channel()
        self.msg('SCAN {},{}'.format(active_channel.channel_num, 1))
        self.autoscan = True

    def disable_autoscan(self):
        """Disable the autoscan feature of the Lakeshore 370.

        Will query active channel to pass already selected channel to SCAN
        command.
        """
        active_channel = self.get_active_channel()
        self.msg('SCAN {},{}'.format(active_channel.channel_num, 0))
        self.autoscan = False

    def chan_num2channel(self, channel_number):
        """Return a Channel Object from LS370.channels by associated Channel number

        :param channel_number: Number associated with Channel to be returned
        :type channl_number: int

        :returns: Channel Object corresponding to channel_number
        :rtype: Channel Object:
        """
        channel_list = [_.channel_num for _ in self.channels]
        idx = channel_list.index(channel_number)
        return self.channels[idx]

    def get_active_channel(self):
        """Query the Lakeshore for which channel it's currently scanning.

        :returns: channel object describing the scanned channel
        :rtype: Channel Object
        """
        resp = self.msg("SCAN?")
        channel_number = int(resp.split(',')[0])
        return self.chan_num2channel(channel_number)

    def set_active_channel(self, channel):
        """Set the active scanner channel.

        Query using SCAN? to determine autoscan parameter and set active
        channel.

        :param channel: Channel number to switch scanner to. 1-8 or 1-16
                        depending on scanner type
        :type channel: int
        """
        resp = self.msg("SCAN?")
        autoscan_setting = resp.split(',')[1]
        self.msg('SCAN {},{}'.format(channel, autoscan_setting))

    # NET?
    def get_network_settings(self):
        pass

    # NETID?
    def get_network_configuration(self):
        pass


class Channel:
    """Lakeshore 370 Channel Object

    :param ls: Lakeshore unit for communication
    :type ls: LS370 Object
    :param channel_num: The channel number (1-8 or 1-16 depending on scanner
                        type)
    :type channel_num: int
    """
    def __init__(self, ls, channel_num):
        self.ls = ls
        self.channel_num = channel_num
        self.enabled = False
        self._get_input_channel_parameter()
        self._get_input_setup()
        self.name = f'Channel {channel_num}'
        #self.tlimit = self.get_temperature_limit()

    def _get_input_channel_parameter(self):
        """Run Input Channel Parameter Query

        ::

          Input channel parameters include:
              off/on - Specifies whether the input/channel is disabled or enabled
                  type off/on - bool
              dwell - Specifies a value for the autoscanning dwell time 1 to 200 s
                  type dwell - int in units of seconds
              pause - Specifies a value for the change pause time: 3 to 200 s
                  type pause - int in units of seconds
              curve number - Specifies which curve the channel uses
                  type curve number - int
              tempco - Sets the temperature coefficient that will be used for
                       temperature control if no curve is selected
                  type tempco - str


        :returns: response from INSET? command

        Reference: LakeShore 370 Manual - page 6-29
        """
        resp = self.ls.msg(f"INSET? {self.channel_num}").split(',')

        self.enabled = bool(int(resp[0]))
        self.dwell = int(resp[1])  # seconds
        self.pause = int(resp[2])  # seconds
        self.curve_num = int(resp[3])
        self.tempco = tempco_key[resp[4]]

        return resp

    def _set_input_channel_parameter(self, params):
        """Set INSET.

        Parameters should be <disabled/enabled>, <dwell>, <pause>, <curve
        number>, <tempco>. Will determine <input/channel> from attributes. This
        allows us to use output from _get_input_channel_parameters directly, as
        it doesn't return <input/channel>.

        :param params: INSET parameters
        :type params: list of str

        :returns: response from ls.msg
        """
        assert len(params) == 5

        reply = [str(self.channel_num)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        return self.ls.msg(f"INSET {param_str}")

    def _get_input_setup(self):
        """Run Resistance Range Query, storing results in human readable format.

        ::

          Input setup parameters include:
              mode - Sensor excitation mode.
                     Measurement input: 0 = Voltage Excitation Mode,
                                        1 = Current Excitation Mode
                     Control input (channel A): 1 = Current Excitation
                  type mode - int
              excitation - Measurement input excitation range
                  type excitation - int
              range - Measurement input resistance. Ignored for control input.
                  type range - int
              autorange - Specifies if auto range is enabled.
                              0 = off,
                              1 = autorange current,
                              2 = ROX102B Autorange (control input only)
                  type autorange - int
              cs shunt - Current source shunt.
                          0 = current source not shunted, excitation on
                          1 = current source shunted, excitation off
                  type cs shunt - int
              units - Specifies the preferred units parameter for sensor readings
                      and for the control setpoint:
                          1 = kelvin,
                          2 = ohms
                  type units - int

        :returns: response from RDGRNG? command

        Reference: LakeShore 370 Manual - page 6-33 - 6-34
        """
        resp = self.ls.msg(f"RDGRNG? {self.channel_num}").split(',')

        _mode = resp[0]
        _excitation = resp[1]
        _range = resp[2]
        _autorange = resp[3]
        _csshunt = resp[4]
        #_units = resp[5]

        self.mode = mode_key[_mode]

        excitation_key = {'0': voltage_excitation_key,
                            '1': current_excitation_key}

        excitation_units_key = {'0': 'volts',
                                '1': 'amps'}

        self.excitation = excitation_key[_mode][int(_excitation)]
        self.excitation_units = excitation_units_key[_mode]

        self.autorange = autorange_key[_autorange]

        self.range = range_key[int(_range)]

        self.csshunt = csshunt_key[_csshunt]

        #self.units = units_key[_units]

        return resp

    def _set_input_setup(self, params):
        """Set RDGRNG.

        Parameters are <mode>, <excitation>, <range>, <autorange>, <cs shunt>.
        Will determine <input/channel> from attributes.

        :param params: RDGRNG parameters
        :type params: list of str

        :returns: response from ls.msg
        """
        assert len(params) == 5

        reply = [str(self.channel_num)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        return self.ls.msg(f"RDGRNG {param_str}")

    # Public API

    def get_excitation_mode(self):
        """Get the excitation mode form RDGRNG?

        :returns: excitation mode, 'current' or 'voltage'
        :rtype: str
        """
        resp = self._get_input_setup()
        self.mode = mode_key[resp[0]]
        return self.mode

    def set_excitation_mode(self, excitation_mode):
        """Set the excitation mode to either voltage excitation or current
        exitation.

        :param excitation_mode: mode we want, must be 'current' or 'voltage'
        :type excitation_mode: str

        :returns: reply from RDGRNG call
        :rtype: str

        """
        assert excitation_mode in ['voltage', 'current']

        resp = self._get_input_setup()
        resp[0] = mode_lock[excitation_mode]

        self.mode = mode_key[resp[0]]

        return self._set_input_setup(resp)

    def get_excitation(self):
        """Get excitation value from RDGRNG?

        :returns: excitation value in volts or amps, depending on mode
        :rtype: float
        """
        resp = self._get_input_setup()
        _mode = resp[0]
        _excitation = resp[1]

        excitation_key = {'0': voltage_excitation_key,
                            '1': current_excitation_key}

        self.excitation = excitation_key[_mode][int(_excitation)]

        return self.excitation

    def set_excitation(self, excitation_value):
        """Set voltage/current exitation to specified value via RDGRNG command.

        :param excitation_value: value in volts/amps of excitation
        :type excitation_value: float

        :returns: response from RDGRNG command
        :rtype: str
        """
        _mode = self.mode

        if _mode == 'voltage':
            excitation_lock = voltage_excitation_lock
        elif _mode == 'current':
            excitation_lock = current_excitation_lock

        closest_value = min(excitation_lock, key=lambda x: abs(x-excitation_value))

        resp = self._get_input_setup()
        resp[1] = str(excitation_lock[closest_value])

        return self._set_input_setup(resp)

    def enable_autorange(self):
        """Enable auto range for channel via RDGRNG command."""
        resp = self._get_input_setup()
        #order of resp args switch for range, autorange in LS370
        resp[3] = '1'     

        #all LS370 channels respond to this command
        for c in self.ls.channels: 
            c.autorange = autorange_key[resp[3]]

        #TODO: move method to LS370 class, fix references in agent
        return self._set_input_setup(resp)

    def disable_autorange(self):
        """Disable auto range for channel via RDGRNG command."""
        resp = self._get_input_setup()
        resp[3] = '0'

        #all LS370 channels respond to this command
        for c in self.ls.channels:
            c.autorange = autorange_key[resp[3]]
       
        #TODO: move method to LS370 class, fix references in agent
        return self._set_input_setup(resp)

    def set_resistance_range(self, resistance_range):
        """Set the resistance range.

        :param resistance_range: range in ohms we want to measure. Doesn't need
                                 to be exactly one of the options on the
                                 lakeshore, will select closest valid range,
                                 though note these are in increments of 2, 6.32, 20, 63.2, etc.
        :type resistance_range: float

        :returns: response from RDGRNG command
        :rtype: str
        """

        def get_closest_resistance_range(num):
            """Gets the closest valid resistance range."""
            ranges = [2.0e-3, 6.32e-3, 20.0e-3, 63.2e-3, 200e-3, 632e-3, 2.0,
                      6.32, 20.0, 63.2, 200, 632, 2e3, 6.32e3, 20.0e3, 63.2e3,
                      200e3, 632e3, 2e6, 6.32e6, 20.0e6, 63.2e6]

            return min(ranges, key=lambda x: abs(x-num))

        _range = get_closest_resistance_range(resistance_range)

        resp = self._get_input_setup()

        #order of range, autorange switched in LS370
        resp[2] = str(range_lock[_range])
        self.range = _range
        return self._set_input_setup(resp)

    def get_resistance_range(self):
        """Get the resistance range.

        :returns: resistance range in Ohms
        :rtype: float
        """
        resp = self._get_input_setup()
        _range = resp[2]
        self.range = range_key[int(_range)]
        return self.range

    def enable_excitation(self):
        """Enable excitation by not shunting the current source via RDGRNG command.

        :returns: state of excitation
        :rtype: str
        """
        resp = self._get_input_setup()
        resp[4] = '0'

        #all LS370 channels respond to this command
        for c in self.ls.channels:
            c.csshunt = csshunt_key[resp[4]]
        
        #TODO: move method to LS370 class, fix references in agent
        return self._set_input_setup(resp)

    def disable_excitation(self):
        """Disable excitation by shunting the current source via RDGRNG command.

        :returns: state of excitation
        :rtype: str
        """
        resp = self._get_input_setup()
        resp[4] = '1'

        #all LS370 channels respond to this command
        for c in self.ls.channels:
            c.csshunt = csshunt_key[resp[4]]
        
        #TODO: move method to LS370 class, fix references in agent
        return self._set_input_setup(resp)

    def get_excitation_power(self):
        """Get the most recent power calculation for the channel via RDGPWR? command.

        :returns: power in Watts
        :rtype: float
        """
        # TODO: Confirm units on this are watts
        resp = self.ls.msg(f"RDGPWR? {self.channel_num}").strip()
        return float(resp)

#    def set_units(self, units):
#        """Set preferred units using INTYPE command.
#
#        :param units: preferred units parameter for sensor readings, 'kelvin'
#                      or 'ohms'
#        :type units: str
#
#        :returns: response from INTYPE command
#        :rtype: str
#        """
#        assert units.lower() in ['kelvin', 'ohms']
#
#        resp = self._get_input_setup()
#        resp[5] = units_lock[units.lower()]
#        return self._set_input_setup(resp)
#
#    def get_units(self):
#        """Get preferred units from INTYPE? command.
#
#        :returns: preferred units
#        :rtype: str
#        """
#        resp = self._get_input_setup()
#        _units = resp[5]
#        self.units = units_key[_units]
#
#        return self.units

    def enable_channel(self):
        """Enable channel using INSET command.

        :returns: response from self._set_input_channel_parameter()
        :rtype: str
        """
        resp = self._get_input_channel_parameter()
        resp[0] = '1'
        self.enabled = True
        return self._set_input_channel_parameter(resp)

    def disable_channel(self):
        """Disable channel using INSET command.

        :returns: response from self._set_input_channel_parameter()
        :rtype: str
        """
        resp = self._get_input_channel_parameter()
        resp[0] = '0'
        self.enabled = False
        return self._set_input_channel_parameter(resp)

    def set_dwell(self, dwell):
        """Set the autoscanning dwell time.

        :param dwell: Dwell time in seconds
        :type dwell: int

        :returns: response from self._set_input_channel_parameter()
        :rtype: str
        """
        assert dwell in range(1, 201), "Dwell must be 1 to 200 sec"

        resp = self._get_input_channel_parameter()
        resp[1] = str(dwell)  # seconds
        self.dwell = dwell  # seconds
        return self._set_input_channel_parameter(resp)

    def get_dwell(self):
        """Get the autoscanning dwell time.

        :returns: the dwell time in seconds
        :rtype: int
        """
        resp = self._get_input_channel_parameter()
        self.dwell = int(resp[1])
        return self.dwell

    def set_pause(self, pause):
        """Set pause time.

        :param pause: Pause time in seconds
        :type pause: int

        :returns: response from self._set_input_channel_parameter()
        :rtype: str
        """
        assert pause in range(3, 201), "Pause must be 3 to 200 sec"

        resp = self._get_input_channel_parameter()
        resp[2] = str(pause)  # seconds
        self.pause = pause  # seconds
        return self._set_input_channel_parameter(resp)

    def get_pause(self):
        """Get the pause time from INSET.

        :returns: the pause time in seconds
        :rtype: int
        """
        resp = self._get_input_channel_parameter()
        self.pause = int(resp[2])  # seconds
        return self.pause

    def set_calibration_curve(self, curve_number):
        """Set calibration curve using INSET.

        Note: If curve doesn't exist, curve number gets set to 0.

        :param curve_number: Curve number for temperature conversion
        :type curve_number: int
        """
        assert curve_number in range(0, 60), "Curve number must from 0 to 59"

        resp = self._get_input_channel_parameter()
        resp[3] = str(curve_number)
        self.curve_num = self.get_calibration_curve()
        return self._set_input_channel_parameter(resp)

    def get_calibration_curve(self):
        """Get calibration curve number using INSET?

        :returns: curve number in use for the channel
        :rtype: int
        """
        resp = self._get_input_channel_parameter()
        self.curve_num = int(resp[3])
        return self.curve_num

    def set_temperature_coefficient(self, coefficient):
        """Set tempertaure coefficient with INSET.

        :param coefficient: set coefficient to be used for temperature control
                            if no curve is selected, either 'negative' or
                            'positive'
        :type coefficient: str

        :returns: response from _set_input_channel_parameter()
        :rtype: str
        """
        assert coefficient in ['positive', 'negative']

        resp = self._get_input_channel_parameter()
        resp[4] = tempco_lock[coefficient]
        self.tempco = coefficient
        return self._set_input_channel_parameter(resp)

    def get_temperature_coefficient(self):
        """Get temperature coefficient from INSET?

        :returns: temperature coefficient
        """
        resp = self._get_input_channel_parameter()
        self.tempco = tempco_key[resp[4]]
        return self.tempco

#    def get_sensor_input_name(self):
#        """Run Sensor Input Name Query
#
#        :returns: response from INNAME? command
#        :rtype: str
#        """
#        resp = self.ls.msg(f"INNAME? {self.channel_num}").strip()
#
#        self.name = resp
#
#        return resp
#
#    def set_sensor_input_name(self, name):
#        """Set sensor input name using INNAME.
#
#        Note: ',' and ';' characters are sanatized from input
#
#        :param name: name to give input channel
#        :type name: str
#        """
#        name = name.replace(',', '').replace(';', '')
#        resp = self.ls.msg(f'INNAME {self.channel_num},"{name}"')
#        self.name = name
#        return resp

    def get_kelvin_reading(self):
        """Get temperature reading from channel.

        :returns: temperature from channel in Kelvin
        :rtype: float
        """
        return float(self.ls.msg(f"RDGK? {self.channel_num}"))

    def get_resistance_reading(self):
        """Get resistence reading from channel.

        :returns: resistance from channel in Ohms
        :rtype: float
        """
        return float(self.ls.msg(f"RDGR? {self.channel_num}"))

    def get_reading_status(self):
        """Get status of input reading.

        :returns: list of errors on reading (or None if no errors)
        :rtype: list of str
        """
        resp = self.ls.msg(f"RDGST? {self.channel_num}")
        error_sum = int(resp)

        errors = {128: "T.UNDER",
                  64: "T.OVER",
                  32: "R.UNDER",
                  16: "R.OVER",
                  8: "VDIF OVL",
                  4: "VMIX OVL",
                  2: "VCM OVL",
                  1: "CS OVL"}

        error_list = []
        for key, value in errors.items():
            if key <= error_sum:
                error_list.append(value)
                error_sum -= key

        assert error_sum == 0

        if len(error_list) == 0:
            error_list = None

        return error_list

#    def get_sensor_reading(self):
#        """Get sensor reading from channel.
#
#        :returns: resistance from channel in Ohms
#        :rtype: float
#        """
#        return float(self.ls.msg(f"SRDG? {self.channel_num}"))

#    def set_temperature_limit(self, limit):
#        """Set temperature limit in kelvin for which to shutdown all control
#        outputs when exceeded. A temperature limit of zero turns the
#        temperature limit feature off for the given sensor input.
#
#        :param limit: temperature limit in kelvin
#        :type limit: float
#
#        :returns: response from TLIMIT command
#        :rtype: str
#        """
#        resp = self.ls.msg(f"TLIMIT {self.channel_num},{limit}")
#        self.tlimit = limit
#        return resp
#
#    def get_temperature_limit(self):
#        """Get temperature limit, at which output controls are shutdown.
#
#        A temperature limit of 0 disables this feature.
#
#        :returns: temperature limit in Kelvin
#        :rtype: float
#        """
#        resp = self.ls.msg(f"TLIMIT? {self.channel_num}").strip()
#        self.tlimit = float(resp)
#        return self.tlimit

    def __str__(self):
        string = "-" * 50 + "\n"
        string += "Channel %s" % (self.channel_num)
        string += "-" * 50 + "\n"
        string += "\t%-30s\t%r\n" % ("Enabled :", self.enabled)
        string += "\t%-30s\t%s %s\n" % ("Dwell:", self.dwell, "seconds")
        string += "\t%-30s\t%s %s\n" % ("Pause:", self.pause, "seconds")
        string += "\t%-30s\t%s\n" % ("Curve Number:", self.curve_num)
        string += "\t%-30s\t%s\n" % ("Temperature Coefficient:", self.tempco)
        string += "\t%-30s\t%s\n" % ("Excitation State:", self.csshunt)
        string += "\t%-30s\t%s\n" % ("Excitation Mode:", self.mode)
        string += "\t%-30s\t%s %s\n" % ("Excitation:", self.excitation, self.excitation_units)
        string += "\t%-30s\t%s\n" % ("Autorange:", self.autorange)
        string += "\t%-30s\t%s %s\n" % ("Resistance Range:", self.range, "ohms")
#        string += "\t%-30s\t%s\n" % ("Preferred Units:", self.units)

        return string


class Curve:
    """Calibration Curve class for the LS370."""
    def __init__(self, ls, curve_num):
        self.ls = ls
        self.curve_num = curve_num

        self.name = None
        self.serial_number = None
        self.format = None
        self.limit = None
        self.coefficient = None
        self.get_header()  # populates above values

    def get_header(self):
        """Get curve header description.

        :returns: response from CRVHDR? in list
        :rtype: list of str
        """
        resp = self.ls.msg(f"CRVHDR? {self.curve_num}").split(',')

        _name = resp[0].strip()
        _sn = resp[1].strip()
        _format = resp[2]
        _limit = float(resp[3])
        _coefficient = resp[4]

        self.name = _name
        self.serial_number = _sn

        self.format = format_key[_format]

        self.limit = _limit
        self.coefficient = tempco_key[_coefficient]

        return resp

    def _set_header(self, params):
        """Set the Curve Header with the CRVHDR command.

        Parameters should be <name>, <SN>, <format>, <limit value>,
        <coefficient>. We will determine <curve> from attributes. This
        allows us to use output from get_header directly, as it doesn't return
        the curve number.

        <name> is limited to 15 characters. Longer names take the fist 15 characters
        <sn> is limited to 10 characters. Longer sn's take the last 10 digits

        :param params: CRVHDR parameters
        :type params: list of str

        :returns: response from ls.msg
        """
        assert len(params) == 5

        _curve_num = self.curve_num
        _name = params[0][:15]
        _sn = params[1][-10:]
        _format = params[2]
        assert _format.strip() in ['3', '4']
        _limit = params[3]
        _coeff = params[4]
        assert _coeff.strip() in ['1', '2']

        return self.ls.msg(f'CRVHDR {_curve_num},{_name},{_sn},{_format},{_limit},{_coeff}')

    def get_name(self):
        """Get the curve name with the CRVHDR? command.

        :returns: The curve name
        :rtype: str
        """
        self.get_header()
        return self.name

    def set_name(self, name):
        """Set the curve name with the CRVHDR command.

        :param name: The curve name, limit of 15 characters, longer names get truncated
        :type name: str

        :returns: the response from the CRVHDR command
        :rtype: str
        """
        resp = self.get_header()
        resp[0] = name.upper()
        self.name = resp[0]
        return self._set_header(resp)

    def get_serial_number(self):
        """Get the curve serial number with the CRVHDR? command."

        :returns: The curve serial number
        :rtype: str
        """
        self.get_header()
        return self.serial_number

    def set_serial_number(self, serial_number):
        """Set the curve serial number with the CRVHDR command.

        :param serial_number: The curve serial number, limit of 10 characters,
                              longer serials get truncated
        :type name: str

        :returns: the response from the CRVHDR command
        :rtype: str
        """
        resp = self.get_header()
        resp[1] = serial_number
        self.serial_number = resp[1]
        return self._set_header(resp)

    def get_format(self):
        """Get the curve data format with the CRVHDR? command."

        :returns: The curve data format
        :rtype: str
        """
        self.get_header()
        return self.format

    def set_format(self, _format):
        """Set the curve format with the CRVHDR command.

        :param _format: The curve format, valid formats are:
                          "Ohm/K (linear)"
                          "log Ohm/K (linear)"
                          "Ohm/K (cubic spline)"
        :type name: str

        :returns: the response from the CRVHDR command
        :rtype: str
        """
        resp = self.get_header()

        assert _format in format_lock.keys(), "Please select a valid format"

        resp[2] = format_lock[_format]
        self.format = _format
        return self._set_header(resp)

    def get_limit(self):
        """Get the curve temperature limit with the CRVHDR? command.

        :returns: The curve temperature limit
        :rtype: str
        """
        self.get_header()
        return self.limit

    def set_limit(self, limit):
        """Set the curve temperature limit with the CRVHDR command.

        :param limit: The curve temperature limit
        :type limit: float

        :returns: the response from the CRVHDR command
        :rtype: str
        """
        resp = self.get_header()
        resp[3] = str(limit)
        self.limit = limit
        return self._set_header(resp)

    def get_coefficient(self):
        """Get the curve temperature coefficient with the CRVHDR? command.

        :returns: The curve temperature coefficient
        :rtype: str
        """
        self.get_header()
        return self.coefficient

    def set_coefficient(self, coefficient):
        """Set the curve temperature coefficient with the CRVHDR command.

        :param coefficient: The curve temperature coefficient, either 'positive' or 'negative'
        :type limit: str

        :returns: the response from the CRVHDR command
        :rtype: str
        """
        assert coefficient in ['positive', 'negative']

        resp = self.get_header()
        resp[4] = tempco_lock[coefficient]
        self.tempco = coefficient
        return self._set_header(resp)

    def get_data_point(self, index):
        """Get a single data point from a curve, given the index, using the
        CRVPT? command.

        The format for the return value, a 2-tuple of floats, is chosen to work
        with how the get_curve() method later stores the entire curve in a
        numpy structured array.

        :param index: index of breakpoint to query
        :type index: int

        :returns: (units, temperature) values for the given breakpoint
        :rtype: 3-tuple of floats
        """
        resp = self.ls.msg(f"CRVPT? {self.curve_num},{index}").split(',')
        _units = float(resp[0])
        _temp = float(resp[1])
        return (_units, _temp)

    def _set_data_point(self, index, units, kelvin, curvature=None):
        """Set a single data point with the CRVPT command.

        :param index: data point index
        :type index: int
        :param units: value of the sensor units to 6 digits
        :type units: float
        :param kelvin: value of the corresponding temp in Kelvin to 6 digits
        :type kelvin: float

        :returns: response from the CRVPT command
        :rtype: str
        """
        resp = self.ls.msg(f"CRVPT {self.curve_num}, {index}, {units}, {kelvin}")
        return resp

    # Public API Elements
    def get_curve(self, _file=None):
        """Get a calibration curve from the LS370.

        If _file is not None, save to file location.
        
        :param _file: the file to load the calibration curve from
        :type _file: str
        """
        breakpoints = []
        for i in range(1, 201):
            x = self.get_data_point(i)
            if x[0] == 0:
                break
            breakpoints.append(x)

        struct_array = np.array(breakpoints, dtype=[('units', 'f8'),
                                                    ('temperature', 'f8')])

        self.breakpoints = struct_array

        if _file is not None:
            with open(_file, 'w') as f:
                f.write('Sensor Model:\t' + self.name + '\r\n')
                f.write('Serial Number:\t' + self.serial_number + '\r\n')
                f.write('Data Format:\t' + format_lock[self.format] + f'\t({self.format})\r\n')

                #TODO: shouldn't this be the curve_header limit?
                #above is done ZA 20200405
                f.write('SetPoint Limit:\t%s\t(Kelvin)\r\n' % '%0.4f' % self.limit)
                f.write('Temperature coefficient:\t' + tempco_lock[self.coefficient] + f' ({self.coefficient})\r\n')
                f.write('Number of Breakpoints:\t%s\r\n' % len(self.breakpoints))
                f.write('\r\n')
                f.write('No.\tUnits\tTemperature (K)\r\n')
                f.write('\r\n')
                for idx, point in enumerate(self.breakpoints):
                    f.write('%s\t%s %s\r\n' % (idx+1, '%0.4f' % point['units'], '%0.4f' % point['temperature']))

        return self.breakpoints

    def set_curve(self, _file):
        """Set a calibration curve, loading it from the file.

        :param _file: the file to load the calibration curve from
        :type _file: str

        :returns: return the new curve header, refreshing the attributes
        :rtype: list of str
        """
        with open(_file) as f:
            content = f.readlines()

        header = []
        for i in range(0, 6):
            if i < 2 or i > 4:
                header.append(content[i].strip().split(":", 1)[1].strip())
            else:
                header.append(content[i].strip().split(":", 1)[1].strip().split("(", 1)[0].strip())

        # Skip to the R and T values in the file and strip them of tabs, newlines, etc
        values = []
        for i in range(9, len(content)):
            values.append(content[i].strip().split())

        self.delete_curve()  # remove old curve first, so old breakpoints don't remain

        self._set_header(header[:-1])  # ignore num of breakpoints

        for point in values:
            print("uploading %s"%point)
            self._set_data_point(point[0], point[1], point[2])

        # refresh curve attributes
        self.get_header()
        self._check_curve(_file)

    def _check_curve(self, _file):
        """After setting a data point for calibration curve,
        use CRVPT? command from get_data_point() to check
        that all points of calibration curve  were uploaded.
        If not, re-upload points.

        :param _file: calibration curve file
        :type _file: str
        """

        with open(_file) as f:
            content = f.readlines()

        #skipping header info
        values = []
        for i in range(9, len(content)):
            values.append(content[i].strip().split()) #data points that should have been uploaded
        
        #TODO: shouldn't this be capped at len(values) + 1?
        #above is done ZA 20200330
        for j in range(1, len(values) + 1):
            try:
                resp = self.get_data_point(j) #response from the 370
                point = values[j-1]
                units = float(resp[0])
                temperature = float(resp[1])
                assert units == float(point[1]), "Point number %s not uploaded"%point[0]
                assert temperature == float(point[2]), "Point number %s not uploaded"%point[0]
                print("Successfully uploaded %s, %s" %(units,temperature))
            #if AssertionError, tell 370 to re-upload points

            #TODO: shouldn't this condition on either units or temperature, not just units?
            #above is done ZA 20200330
            except AssertionError:
                if units != float(point[1]) or temperature != float(point[2]):
         
                    #TODO: fix, could enter infinite loop if always fails 
                    self.set_curve(_file)

        #check that remainining points are zeros
        for j in range(len(values) + 1, 201):
            try:
                resp = self.get_data_point(j) #response from the 370
                units = float(resp[0])
                temperature = float(resp[1])
                assert units == 0, "Point number %s contains nonzero data"%j
                assert temperature == 0, "Point number %s contains nonzero data"%j
            except AssertionError:
                if units != 0 or temperature != 0:

                    #TODO: fix, could enter infinite loop if always fails
                    self.set_curve(_file)

    def delete_curve(self):
        """Delete the curve using the CRVDEL command.

        :returns: the response from the CRVDEL command
        :rtype: str
        """
        resp = self.ls.msg(f"CRVDEL {self.curve_num}")
        self.get_header()
        return resp

    def __str__(self):
        string = "-" * 50 + "\n"
        string += "Curve %d: %s\n" % (self.curve_num, self.name)
        string += "-" * 50 + "\n"
        string += "  %-30s\t%r\n" % ("Serial Number:", self.serial_number)
        string += "  %-30s\t%s (%s)\n" % ("Format :", format_lock[self.format], self.format)
        string += "  %-30s\t%s\n" % ("Temperature Limit:", self.limit)
        string += "  %-30s\t%s\n" % ("Temperature Coefficient:", self.coefficient)

        return string

#TODO: make new Analog class. Too many firmware distictions to group both Heater and Analog outputs
#into same class of objects
class Heater:
    """Heater class for LS370 control

    :param ls: the lakeshore object we're controlling
    :type ls: Lakeshore370.LS370
    """
    def __init__(self, ls):
        self.ls = ls

        self.mode = None
        self.input = None
        #self.powerup = None in 370, powerup is always disabled
        self.polarity = None
        self.filter = None
        self.delay = None
        self.units = None

        self.range = None

        self.resistance = None     #only for output = 0
        #self.max_current = None   in 370, there is only htrrng limit and curve limit 
        #self.max_user_current = None  not in 370
        self.rng_limit = None
        self.display = None

        self._get_output_mode()
        self.get_heater_range()
        self.get_heater_setup()

    def _get_output_mode(self):
        """Query the heater mode using the CMODE?, CPOL?, CSET? commands.

        :returns: 6-tuple with output mode, polarity, input channel, 
            unfiltered/filtered, heater units (kelvin, ohms), and autoscanning delay time.
        :rtype: tuple
        """
        _mode = self.ls.msg('CMODE?')
        self.mode = output_modes[_mode]
        self.polarity = self.ls.msg('CPOL?')

        resp = self.ls.msg('CSET?').split(',')
        self.input = resp[0]
        self.filter = resp[1]
        self.units = units_key[resp[2]]
        self.delay = resp[3]

        return [self.mode, self.polarity, self.input, self.filter, self.units, self.delay]

    def _set_output_mode(self, params):
        """Set the output mode of the heater with the CMODE, CPOL, CSET commands.

        Parameters should be <mode>, <polarity>, <input/channel>, <filter>, <units>,
        <delay>.

        :param params: CMODE/CPOL/CSET parameters
        :type params: list of str

        :returns: response from ls.msg
        """
        assert len(params) == 6

        self.ls.msg(f'CMODE {params.pop(0)}')
        self.ls.msg(f'CPOL {params.pop(0)}')
        
        reply = params + [heater_display_lock[self.display], heater_range_lock[self.rng_limit],
                str(self.resistance)]

        param_str = ','.join(reply)
        return self.ls.msg(f"CSET {param_str}")

    def get_heater_setup(self):
        """Gets Heater setup params with the CSET? command.

        :return resp: List of values that have been returned from the Lakeshore.
        """
        resp = self.ls.msg("CSET?").split(',')

        self.display = heater_display_key[resp[4]]
        self.rng_limit = heater_range_key[resp[5]] 
        self.resistance = float(resp[6])
        #self.max_current = int(resp[1])
        #self.max_user_current = float(resp[2].strip('E+'))

        return [self.display, self.rng_limit, self.resistance]

    def _set_heater_setup(self, params):
        """
        Sets the heater setup using the CSET command.

        Params must be a list with the parameters:
            <current/power>:    Specifies if heater display is current or power.
                                1=current, 2=power.
            <rng_limit>: Max heater range; ranges according to HTRRNG command
            <heater resistance>:    Heater load in Ohms (Sample);
                                    1=25 Ohms, 2=50 Ohms (warmp-up)

        :param params:
        :return:
        """
        assert len(params) == 3

        reply = [self.input, self.filter, units_lock[self.units], self.delay] + params
        param_str = ','.join(reply)
        return self.ls.msg("CSET {}".format(param_str))

    def get_mode(self):
        """Set output mode with CMODE? commnd.

        :returns: The output mode
        :rtype: str
        """
        self._get_output_mode()
        return self.mode

    def set_mode(self, mode):
        """Set output mode with CMODE commnd.

        :param mode: control mode for heater, see page 6-24 pf Lakeshore 370 manual
        :type mode: str

        :returns: the response from the OUTMODE command
        """
        # TODO: Make assertions check specific output and it's validity in mode selection
        assert mode.lower() in output_modes_lock.keys(), f"{mode} not a valid mode"

        resp = self._get_output_mode()
        resp[0] = output_modes_lock[mode.lower()]
        self.mode = mode
        return self._set_output_mode(resp)

    def get_manual_out(self):
        resp = self.ls.msg("MOUT?")
        return float(resp)

    def get_input_channel(self):
        """Get the control channel with the CSET? command.

        :returns: The control channel
        :rtype: str
        """
        self._get_output_mode()
        return self.input

    def set_input_channel(self, _input):
        """Set the control channel with the CSET command.

        :param _input: specifies which input or channel to control from
        :type _input: str or int
        """
        #ZA fixed to range(1, 17) from range(17). deleted 'A'
        assert int(_input) in range(1, 17), f"{_input} not a valid input/channel"

        resp = self._get_output_mode()
        resp[2] = str(_input)
        self.input = str(_input)
        return self._set_output_mode(resp)

    def get_powerup(self):
        pass

    def set_powerup(self, powerup):
        """
        :param powerup: specifies whether the output remains on or shuts off
                        after power cycle. True for on after powerup
        :type powerup: bool
        """
        # assert powerup in [True, False], f"{powerup} not valid powerup parameter"
        # set_powerup = str(int(powerup))
        #
        pass

    def get_polarity(self):
        pass

    def set_polarity(self):
        """
        :param polarity: specifies output polarity: 'unipolar' or 'bipolar'
        :type polarity: str
        """
        # polarity_key = {0: 'unipolar', 1: 'bipolar'}
        # polarity_lock = {v:k for k, v in polarity_key.items()}
        #
        # assert polarity in polarity_lock.keys(), f"{polarity} not a valid polarity parameter"
        #
        # {polarity_lock[polarity]}
        pass

    def get_filter(self):
        pass

    def set_filter(self, _filter):
        """
        :param _filter: specifies controlling on unfiltered or filtered readings, True = filtered, False = unfiltered
        :type _filter: bool
        """
        # assert _filter in [True, False], f"{_filter} not valid filter parameter"
        # set_filter = str(int(_filter))
        #
        pass

    def get_units(self):
        """Get the setpoint units with the CSET? command.

        :returns: units, either 'kelvin' or 'ohms'
        :rtype: str
        """
        self._get_output_mode()
        return self.units

    def set_units(self, units):
        """Set the setpoint units with the CSET command.

        :param units: units, either 'kelvin' or 'ohms'
        :type units: str
        """
        assert units.lower() in units_lock.keys(), f"{units} not a valid unit"

        resp = self._get_output_mode()
        resp[4] = units_lock[units.lower()]
        self.units = units.lower()
        return self._set_output_mode(resp)

    def get_delay(self):
        pass

    def set_delay(self, delay):
        """
        :param delay: delay in seconds for setpoint change during autoscanning, 1-255 seconds
        :type delay: int
        """
        # assert delay in range(1, 256), f"{delay} not a valid delay parameter"
        #
        pass

    def set_heater_display(self, display):
        """
        :param display: Display mode for heater. Can either be 'current' or 'power'.
        :type display: string
        """
        assert display.lower() in heater_display_lock.keys(), f"{display} is not a valid display"

        resp = self.get_heater_setup()
        resp[0] = heater_display_lock[display.lower()]

        self._set_heater_setup(resp)

        self.get_heater_setup()

    # Presumably we're going to know and have set values for heat resistance,
    # max current, etc, maybe that'll simplify this in the future.
    def set_heater_output(self, output, display_type=None):
        """Set heater output with MOUT command.

        :param output: heater output value. If display is 'power', value should
                        be in Watts. If 'current', value should be in percent.
        :type output: float
        :param display_type: Display type if you want to set this before setting heater.
                        Can be 'power' or 'current'.
        :type display_type: string

        :returns: heater output
        :rtype: float
        """

        if display_type is not None:
            self.set_heater_display(display_type)

        self.get_heater_range()
        self.get_heater_setup()

        if self.range in ["off", "Off"]:
            print("Heater range is off... Not setting output")
            return False

        # For sample heater
        max_pow = self.range ** 2 * self.resistance

        if self.display == 'power':
            if 0 <= output <= max_pow:
                self.ls.msg(f"MOUT {output}")
                return True
            else:
                print("Cannot set to {} W, max power is {:2e} W".format(
                    output, max_pow))
                return False

        if self.display == 'current':
            if 0 <= output <= 100:
                self.ls.msg(f"MOUT {output}")
                return True
            else:
                print(
                    "Display is current: output must be between 0 and 100")
                return False

    # RAMP, RAMP? - in heater class
    def set_ramp_rate(self, rate):
        pass

    def get_ramp_rate(self, rate):
        pass

    def enable_ramp(self):
        pass

    def disable_ramp(self):
        pass

    # RAMPST?
    def get_ramp_status(self):
        pass

    # RANGE
    def set_heater_range(self, _range):
        """Set heater range with HTRRNG command.

        :param _range: heater range
        :type _range: float or str (for "On" "Off")

        :returns: heater range in amps
        :rtype: float
        """
        assert _range in heater_range_lock.keys() or str(_range).lower() in ['on', 'off'], 'Not a valid heater Range'

        if str(_range).lower() == 'off':
            _range = "Off"
        if str(_range).lower() == 'on':
            _range = "On"

        resp = self.ls.msg(f"HTRRNG {heater_range_lock[_range]}").strip()
        
        # refresh self.heater value with RANGE? query
        self.get_heater_range()

    def get_heater_range(self):
        """Get heater range with HTRRNG? command.

        :returns: heater range in amps
        :rtype: float
        """
        resp = self.ls.msg(f"HTRRNG?").strip()

        self.range = heater_range_key[resp]

        return self.range

    # SETP - heater class, uses self.units to interpret value
    def set_setpoint(self, value):
        self.ls.msg(f"SETP {value}")

    # SETP? - heater class, uses self.units to interpret value
    def get_setpoint(self):
        resp = self.ls.msg(f"SETP?")
        return resp

    # STILL - heater class?
    def set_still_output(self, value):
        self.ls.msg(f"STILL {value}")

    # STILL? - heater_class?
    def get_still_output(self):
        resp = self.ls.msg(f"STILL?")
        return resp

    # ANALOG, ANALOG?, AOUT?
    # TODO: read up on what analog output is used for, pretty sure just another output
    def get_analog_output(self):
        pass

    def set_analog_output(self):
        pass

    # PID
    def set_pid(self, P, I, D):
        """Set PID parameters for closed loop control.

        :params P: proportional term in PID loop
        :type P: float
        :params I: integral term in PID loop
        :type I: float
        :params D: derivative term in PID loop
        :type D: float

        :returns: response from PID command
        :rtype: str
        """
        assert float(P) <= 1000 and float(P) >= 0
        assert float(I) <= 10000 and float(I) >= 0
        assert float(D) <= 2500 and float(D) >= 0

        resp = self.ls.msg(f"PID {P},{I},{D}")
        return resp

    # PID?
    def get_pid(self):
        """Get PID parameters with PID? command.

        :returns: P, I, D
        :rtype: float, float, float
        """
        resp = self.ls.msg("PID?").split(',')
        return float(resp[0]), float(resp[1]), float(resp[2])


if __name__ == "__main__":
    ls = LS370(sys.argv[1])
    print(ls.msg('*IDN?'))
    print(f'LS370 successfully initialized at port {sys.argv[1]}')
