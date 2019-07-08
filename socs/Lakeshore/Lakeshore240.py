#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Fri Feb 23 14:15:51 2018

@author: jacoblashner
"""

from serial import Serial
from serial.serialutil import SerialException
import time
import sys
import numpy as np
from collections import OrderedDict
import socket
from typing import List


BUFF_SIZE = 1024

try:
    from tqdm import *
except ModuleNotFoundError:
    tqdm = lambda x: x

class Module:
    """
        Allows communication to Lakeshore Module.
        Contains list of inputs which can be read from.
    """

    def __init__(self, port='/dev/tty.SLAB_USBtoUART', baud=115200, timeout=10):
        """
            Establish Serial communication and initialize channels.
        """

        # Running with a simulator
        # Make sure to write over tcp instead of serial.
        if port[:6] == 'tcp://':
            self.simulator = True
            address, socket_port = port[6:].split(':')
            socket_port = int(socket_port)

            for p in range(socket_port, socket_port + 10):
                try:
                    print(f"Trying to connect on port {p}")
                    self.com = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.com.connect(('localhost', p))
                    print(f"Found connection on port {p}")
                    break
                except ConnectionRefusedError as e:
                    if e.errno == 61:
                        continue
                    else:
                        raise e

        else:
            self.com = Serial(port=port, baudrate=baud, timeout=timeout)
            self.simulator = False

        # First comms usually fails if this is your first time communicating
        # after plugging in the LS240. Try three times, then give up.
        for i in range(3):
            try:
                print('attempt %s'%i)
                idn = self.msg("*IDN?")
                break
            except TimeoutError:
                print("Comms failed on attempt %s"%i)

        self.manufacturer, self.model, self.inst_sn, self.firmware_version = idn.split(',')
        num_channels = int(self.model[-2])

        self.name = self.msg("MODNAME?")

        self.channels: List[Channel] = []
        for i in range(num_channels):
            c = Channel(self, i+1)
            self.channels.append(c)

    def close(self):
        if self.simulator:
            self.com.close()

    def __exit__(self):
        self.close()

    def msg(self, msg):
        """
            Send command or query to module.
            Return response (within timeout) if message is a query.
        """
        if self.simulator:
            message_string = "{};".format(msg)
            self.com.send(message_string.encode())
            resp = ''
            if '?' in msg:
                resp = self.com.recv(BUFF_SIZE).decode()
            return resp

        else:
            # Writes message
            message_string = "{}\r\n;".format(msg).encode()

            # write(message_string)
            self.com.write(message_string)

            # Reads response if queried
            resp = ''
            if "?" in msg:
                resp = self.com.readline()
                resp = str(resp[:-2], 'utf-8')       # Strips terminating chars
                if not resp:
                    raise TimeoutError("Device timed out")

            # Must wait 10 ms before sending another command
            time.sleep(.01)

            return resp

    def set_name(self, name):
        self.name = name
        self.msg("MODNAME {}".format(name))

    def __str__(self):
        return "{} ({})".format(self.name, self.inst_sn)


# ==============================================================================
# Lots of stuff to convert between integers that are read by the module
# and what the integers actually stand for
# ==============================================================================

# To convert from int representation to string
sensorStrings = ["None","Diode", "PlatRTC", "NTCRTC"]
unitStrings = ["None", "Kelvin", "Celsius", "Sensor", "Fahrenheit"]

# To convert from int representation to excitation or range
# use:   ranges[sensorType][range]
excitations = [[10e-6], [1e-3], [1e-3, 300e-6, 100e-6, 30e-6, 10e-6, 3e-6, 1e-6, 300e-9, 100e-9]]
ranges = [[7.5], [1e3], [10, 30, 100, 300, 1e3, 3e3, 10e3, 30e3, 100e3]]

units_key = {1: 'K', 2: 'C', 3: 'S', 4: 'F'}


class Channel:
    """
        Object for each channel of the lakeshore module

        Properties
        --------------
        :channel_num: The number of the channel (1-8). This should not be changed once set
        :name: Specifies name of channel
        :sensor (int): 1 = Diode, 2 = PlatRTC, 3 = NTC RTD
        :auto_range: Specifies if channel should use autorange (1,0).
        :range: Specifies range if auto_range is false (0-8). Range is accoriding to Lakeshore docs.
        :current_reversal: Specifies if current reversal should be used (0, 1). Should be 0 for diode.
        :unit: 1 = K, 2 = C, 3 = Sensor, 4 = F
        :enabled: Sets whether channel is enabled. (1,0)

    """
    def __init__(self, ls, channel_num):
        self.ls = ls
        self.channel_num = channel_num

        # Reads channel info from device
        response = self.ls.msg("INTYPE? {}".format(self.channel_num))
        data = response.split(',')

        self._sensor = int(data[0])
        self._auto_range = int(data[1])
        self._range = int(data[2])
        self._current_reversal = int(data[3])
        self._unit = int(data[4])
        self._enabled = int(data[5])

        response = self.ls.msg("INNAME? %d" % (self.channel_num))
        self.name = response.strip()

    def set_values(self, sensor=None, auto_range=None, range=None,
                   current_reversal=None, unit=None, enabled=None, name=None):
        """
            Sets Channel parameters after validation.
        """
        # Checks to see if values are valid
        if sensor is not None:
            if sensor in [1, 2]:
                self._sensor = sensor
                self._range = 0
            elif sensor == 3:
                self._sensor = sensor
            else:
                print("Sensor value must be 1,2, or 3.")

        if auto_range is not None:
            if auto_range in [0, 1]:
                self._auto_range = auto_range
            else:
                print("auto_range must be 0 or 1.")

        if range is not None:
            if self._sensor == 3 and range in [0, 1, 2, 3, 4, 5, 6, 7, 8]:
                self._range = range
            elif range == 0:
                self._range = range
            else:
                print("Range must be 0 for Diode or Plat RTD, or 0-8 for a NTC RTD")

        if current_reversal is not None:
            if current_reversal in [0, 1]:
                self._current_reversal = current_reversal
            else:
                print("current_reversal must be 0 or 1.")

        if unit is not None:
            if unit in [1, 2, 3, 4]:
                self._unit = unit
            else:
                print("unit must be 1, 2, 3, or 4")

        if enabled is not None:
            if enabled in [0, 1]:
                self._enabled = enabled
            else:
                print("enabled must be 0 or 1")

        if name is not None:
            self.name = name

        # Writes new values to module
        self.ls.msg("INNAME {},{!s}".format(self.channel_num, self.name))

        input_type_message = "INTYPE "
        input_type_message += ",".join(["{}".format(c) for c in [ self.channel_num, self._sensor, self._auto_range,
                                                                    self._range, self._current_reversal, self._unit,
                                                                    int(self._enabled)]])
        self.ls.msg(input_type_message)

    def read_curve(self):
        # Reads curve
        breakpoints = []
        for i in range(1, 201):
            resp = self.ls.msg("CRVPT? {},{}".format(self.channel_num, i))
            unit, temp = resp.split(',')
            if float(unit) == 0.0:
                break
            breakpoints.append((float(unit), float(temp)))

        resp = self.ls.msg("CRVHDR? {}".format(self.channel_num)).split(',')

        header = {
            "Sensor Model": resp[0],
            "Serial Number": resp[1],
            "Data Format": int(resp[2]),
            "SetPoint Limit": float(resp[3]),
            "Temperature Coefficient": int(resp[4]),
            "Number of Breakpoints": len(breakpoints)
        }

        self.curve = Curve(header=header, breakpoints=breakpoints)

    def get_reading(self, unit=None):
        """Get a reading from the channel in the specified units.

        If no unit is provided, use the one determined by the channel settings.

        Args:
            unit (str): Units for reading, options are Kelvin (K), Celcius (C),
                        Fahrenheit (F), or Sensor (S)

        """
        if unit is None:
            u = units_key[self._unit]
        else:
            u = unit

        assert u.upper() in ['K', 'C', 'F', 'S']

        message = "{}RDG? {}".format(u, self.channel_num)
        response = self.ls.msg(message)

        return float(response)

    def load_curve_point(self, n, x, y):
        """ Loads point n in the curve for specified channel"""
        message = "CRVPT "
        message += ",".join([str(c) for c in [self.channel_num, n, x, y]])
        self.ls.msg(message)

    def load_curve(self, filename):
        """Upload calibration curve to channel from file.

        Args:
            filename (str): Calibration file for upload.

        """
        self.curve = Curve(filename=filename)
        hdr = self.curve.header
        keys = list(hdr)

        #loads header
        cmd = "CRVHDR {}".format(self.channel_num)
        for key in keys[:5]:
            cmd += ",{}".format(hdr[key])
        print(cmd)
        self.ls.msg(cmd)

        bps = self.curve.breakpoints
        assert len(bps) <= 200, "Curve must have 200 breakpoints or less"

        print ("Loading Curve to {}".format(self.name))
        for i in range(200):
            if i < len(bps):
                self.load_curve_point(i+1, bps[i][0], bps[i][1])
            else:
                self.load_curve_point(i+1, 0, 0)
        print("Curve loaded")

    def delete_curve(self):
        """Delete calibration curve from channel."""
        cmd = "CRVDEL {}".format(self.channel_num)
        self.ls.msg(cmd)

    def __str__(self):
        string = "-" * 40 + "\n"
        string += "{} -- Channel {}: {}\n".format(self.ls.inst_sn, self.channel_num, self.name)
        string += "-"*40 + "\n"

        string += "{!s:<18} {!s:>13}\n".format("Enabled:", self._enabled)
        string += "{!s:<18} {!s:>13} ({})\n".format("Sensor:", self._sensor, sensorStrings[self._sensor])
        string += "{!s:<18} {!s:>13}\n".format("Auto Range:", self._auto_range)

        range_unit = "V" if self._sensor == 1 else "Ohm"
        string += "{!s:<18} {!s:>13} ({} {})\n".format("Range:", self._range, ranges[self._sensor-1][self._range], range_unit)
        string += "{!s:<18} {!s:>13}\n".format("Current Reversal:", self._current_reversal)
        string += "{!s:<18} {!s:>13}\n".format("Units:", units_key[self._unit])

        return string


class Curve:
    """
    Header for calibration curve
    ----------------
    :Sensor Model:      Name of curve
    :Serial Number:        Serial Number
    :Data Format:    2 = V:K, 3 = Ohms:K, 4 = log(Ohms):K
    :SetPoint Limit:     Temperature Limit (in K)
    :Temperature Coefficient:     1 = negative, 2 = positive
    :Number of Breakpoints:     Number of curve points
    """
    def __init__(self, filename=None, header=None, breakpoints=None):

        if filename is not None:
            self.load_from_file(filename)
        else:
            if header and breakpoints:
                self.header = header
                self.breakpoints = breakpoints
            else:
                raise Exception("Must give either filename or header and breakpoints")

    def write_to_file(self, filename):
        with open(filename, 'w') as file:

            keys = list(self.header)
            for k in keys:
                print(k, self.header[k])
                file.write("{}:\t{}\n".format(k, self.header[k]))

            file.write('\n')
            file.write('No.\tUnits\tTemperature (K)\n')
            file.write('\n')

            for i,bp in enumerate(self.breakpoints):
                file.write('{}\t{:.4f} {:.4f}\n'.format(i+1, bp[0], bp[1]))

    def load_from_file(self, filename):
        with open(filename, 'r') as file:
            content = file.readlines()

        self.header = OrderedDict({})
        for line in content:
            if line.strip()=='':
                break
            key, v = line.split(':')
            val = v.split('(')[0].strip()
            self.header[key] = val

        self.breakpoints = []
        for line in content[9:]:
            num, unit, temp = line.split()
            self.breakpoints.append((float(unit), float(temp)))

    def __str__(self):
        string = ""
        for key, val in self.header.items():
            string += "%-15s: %s\n"%(key, val)
        return string

if __name__ == "__main__":
    ls = Module(port=sys.argv[1])
    print (ls)
