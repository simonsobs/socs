#!/usr/bin/python3
#contributors: zatkins, bkoopman, sbhimani

import math
import numpy as np
import serial

import time 
import sys

# proxy for agent
sys.path.append('/home/zatkins/repos/stslab/testbed')

# helper dicts
sensor_key = {
    '0': 'disabled',
    '1': 'diode',
    '2': 'platinum rtd',
    '3': 'ntc rtd',
    '4': 'thermocouple',
    '5': 'capacitance'
}
sensor_lock = {v:k for k, v in sensor_key.items()}

units_key = {
    '1': 'kelvin',
    '2': 'celsius',
    '3': 'sensor'
}
units_lock = {v:k for k, v in units_key.items()}

tempco_key = {
    '1': 'negative',
    '2': 'positive'
}
tempco_lock = {v:k for k, v in tempco_key.items()}

format_key = {
    '1': "mV/K (linear)",
    '2': "V/K (linear)",
    '3': "Ohm/K (linear)",
    '4': "log Ohm/K (linear)"
}
format_lock = {v:k for k, v in format_key.items()}

output_modes_key = {
    '0': 'off', 
    '1': 'closed loop', 
    '2': 'zone', 
    '3': 'open loop', 
    '4': 'monitor out', 
    '5': 'Warm up'
}
output_modes_lock = {v.lower():k for k, v in output_modes_key.items()}

channel_key = {
    '0': 'none',
    '1': 'A',
    '2': 'B',
    '3': 'C',
    '4': 'D'
}
channel_lock = {v:k for k,v in channel_key.items()}

heater_display_key = {
    '1': 'current',
    '2': 'power'
}
heater_display_lock = {v:k for k,v in heater_display_key.items()}

max_current_key = {
    '0': 'User',
    '1': .707,
    '2': 1.,
    '3': 1.141,
    '4': 2
}
max_current_lock = {v:k for k, v in max_current_key.items()}

heater_range_key = {
    "0": "off",
    "1": "low",
    "2": "medium",
    "3": "high"
}
heater_range_lock = {v:k for k, v in heater_range_key.items()}

ramp_key = {
    '0': 'off',
    '1': 'on'
}
ramp_lock = {v:k for k,v in ramp_key.items()}

# main class - Lakeshore 336 driver
class LS336:
    '''
    Implements a lakeshore 336 box to interface with client scripts. Only contains locally relevant information; namely, port parameters. The state of the device is not stored locally to avoid the potential for inconsistent information. Device status can always be accessed (accurately) through a msg.    
    '''
    #Constructor and instance variables

    def __init__(self, port, timeout = 1.0):

        # LS336 defaults
        self.baud = 57600
        self.bytesize = serial.SEVENBITS
        self.parity = serial.PARITY_ODD
        self.stopbits = serial.STOPBITS_ONE
        self.term = '\r\n'
        self.std_delay = 0.06

        self.port = port
        self.timeout = timeout
        self.comm = serial.Serial(self.port, self.baud, self.bytesize, self.parity, self.stopbits, timeout)
        self.comm.close()

        self.id = self.get_id()
        print(self.id) #print idenfitication information to see if working

        # Get Channels
        inps = ['A','B','C','D']
        self.channels = {inp:Channel(self, inp) for inp in inps}

        # Get Heaters
        htrs = ['1', '2']
        self.heaters = {out:Heater(self, out) for out in htrs}

    #Instance methods

    def msg(self, cmd, delay = None):
        r'''
        msgs character string cmd to port comm, including commands and queries.

        Parameters
        ------
        comm : serial.Serial object
            The port on the local machine attached to the device. See pyserial documentation. Must be configured according to the lakeshore manual.

        cmd : string
            The character sequence to send to the device. Must be in the device proprietary library, available in the lakeshore manual.

        delay : float or int
            After writing, the function will lock out the kernel for delay seconds. Within a script, this prevents too many cmds being written to the device too quickly.

        term : str
            Terminating character sequence appended to cmd. Indicates end of message.
        '''
        if not delay: delay = self.std_delay

        cmd = cmd + self.term
        bcmd = cmd.encode()

        if not self.comm.is_open:
            self.comm.open()
        self.comm.write(bcmd)
        
        time.sleep(delay)

        out = ''

        if '?' in cmd:
            out = self.read()

        self.comm.close()
        return out 

    def read(self, size = None, delay = None):
        r'''
        Reads data from the device attached to port comm. Implemented via pyserial 'read_until' command: reads until receives '\n'; every lakeshore response terminates with '\r\n'.

        Parameters
        ------
        comm : serial.Serial object
            The port on the local machine attached to the device. See pyserial documentation. Must be configured according to the lakeshore manual.
        
        size : int, optional
            Number of bytes to read. If provided, may be less than full message length.
        
        Returns
        ------
        out : str
            Message from lakeshore device.
        '''        
        if not delay: delay = self.std_delay
      
        if not self.comm.is_open:
            self.comm.open()
        
        out = self.comm.read_until(size = size).strip().decode()
        self.comm.close()

        time.sleep(delay)

        return out

    def read_size(self, size = 256, delay = None):
        r'''
        Reads data from the device attached to port comm. Implemented via pyserial 'read' command: reads until receives size bytes.

        Parameters
        ------
        comm : serial.Serial object
            The port on the local machine attached to the device. See pyserial documentation. Must be configured according to the lakeshore manual.
        
        size : int, optional
            Number of bytes to read. If provided, may be less than full message length.
        
        Returns
        ------
        out : str
            Message from lakeshore device.
        '''       
        if not delay: delay = self.std_delay
 
        if not self.comm.is_open:
            self.comm.open()
        
        out = self.comm.read(size = size).strip().decode()
        self.comm.close()
        
        time.sleep(delay)
        
        return out

    def get_id(self):
        '''Get identification information of the Lakeshore module'''
        return self.msg('*IDN?')

    def get_kelvin(self, inp):
        '''Return a temperature reading of the specified input ('A', 'B', 'C', or 'D')
        or '0' for all inputs

        Parameters
        ----------
        inp : str
            channel to query

        Returns
        -------
        str
            plain text of temperature reading

        Raises
        ------
        ValueError
            Invalid input channel arguments
        '''
        if inp not in ['0', 'A', 'B', 'C', 'D']:
            raise ValueError(f'invalid input in msg_kelvin: {inp}')

        return self.msg(f'KRDG? {inp}')
        
    def get_sensor(self, inp):
        '''Return a sensor reading of the specified input ('A', 'B', 'C', or 'D')
        or '0' for all inputs

        Parameters
        ----------
        inp : str
            channel to query

        Returns
        -------
        str
            plain text of temperature reading

        Raises
        ------
        ValueError
            Invalid input channel arguments
        '''     
        if inp not in ['0', 'A', 'B', 'C', 'D']:
            raise ValueError(f'invalid input in msg_sensor: {inp}')

        return self.msg(f'SRDG? {inp}')

    def get_heater_range(self, htr):
        return self.heaters[htr].get_heater_range()

    def get_max_current(self, htr):
        return self.heaters[htr].get_max_current()

    def get_heater_percent(self, htr):
        return self.heaters[htr].get_heater_percent()

    def get_setpoint(self, htr):
        return self.heaters[htr].get_setpoint()

class Channel:

    def __init__(self, ls, _input):
        '''Channel class for LS336

        Parameters
        ----------
        ls : LS336 object
            The parent LS336 device
        _input : str
            The channel we are building ('A', 'B', 'C', or 'D')
        '''
        assert _input in ['A', 'B', 'C', 'D']

        self.ls = ls
        self.input = _input
        self.num = channel_lock[self.input]
        self.get_input_type()
        self.get_input_curve()
        self.get_input_name()
        self.get_T_limit()

    def get_input_type(self):
        '''Return sensor metadata, <sensor type>, <autorange>, <range>,
        <compensation>, and <units>. For diodes, only sensor type and 
        units are relevant.

        Returns
        -------
        list
            <sensor type>, <autorange>, <range>, <compensation>, and <units>
        '''
        resp = self.ls.msg(f'INTYPE? {self.input}').split(',')

        self.sensor_type = sensor_key[resp[0]]
        self.autorange = int(resp[1])
        self.range = int(resp[2])
        self.compensation = int(resp[3])
        self.units = units_key[resp[4]]

        return resp

    def _set_input_type(self, params):
        '''Assign sensor metadata, <sensor type>, <autorange>, <range>,
        <compensation>, and <units>. For diodes, only sensor type and 
        units are relevant.

        Parameters
        ----------
        params : list
            <sensor type>, <autorange>, <range>, <compensation>, and <units>
        '''
        assert len(params) == 5

        reply = [str(self.input)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        return self.ls.msg(f"INTYPE {param_str}")

    def get_sensor_type(self):
        '''Get the sensor type of the channel in plain text'''
        self.get_input_type()
        return self.sensor_type

    def set_sensor_type(self, type):
        '''Set the sensor type on the channel

        Parameters
        ----------
        type : str
            Sensor type must be in 'Disabled', 'Diode', 'Platinum RTD',
            'NTC RTD', 'Thermocouple', 'Capacitance'
        '''
        assert type.lower() in sensor_lock

        resp = self.get_input_type()
        resp[1] = sensor_lock[type.lower()]
        self.sensor_type = type.lower()
        return self._set_input_type(resp)

    def get_units(self):
        '''Get the channel preferred units as plain text'''
        self.get_input_type()
        return self.units

    def set_units(self, units):
        '''Set the channel preferred units

        Parameters
        ----------
        unit : str
            Channel preferred units must be in 'Kelvin', 'Celsius, 'Sensor
        '''
        assert units.lower() in units_lock

        resp = self.get_input_type()
        resp[4] = units_lock[units.lower()]
        self.units = units.lower()
        return self._set_input_type(resp)

    def get_input_name(self):
        '''Get the name of the channel shown on front display

        Returns
        -------
        str
            The channel name for display purposes
        '''
        resp = self.ls.msg(f'INNAME? {self.input}').strip()
        self.input_name = resp
        return self.input_name

    def set_input_name(self, name):
        '''Set the name of the channel shown on front display

        Parameters
        ----------
        name : str
            The channel name for display purposes. Only send the first 15 characters
        '''
        name = name[:15]
        self.input_name = name
        resp = self.ls.msg(f'INNAME {self.input},{name}')
        return resp

    def get_input_curve(self):
        '''Return the curve number of the curve assigned to this channel'''
        resp = self.ls.msg(f'INCRV? {self.input}').strip()
        self.input_curve = int(resp)
        return self.input_curve

    def set_input_curve(self, curve_num):
        '''Set the curve number of the curve assigned to this channel'''
        assert curve_num in range(1, 60)

        self.input_curve = curve_num
        resp = self.ls.msg(f'INCRV {self.input},{self.input_curve}')
        return resp

    def get_T_limit(self):
        '''Return the temperature limit above which control outputs assigned this channel
        shut off'''
        resp = self.ls.msg(f'TLIMIT? {self.input}')
        self.T_limit = float(resp)
        return self.T_limit

    def set_T_limit(self, limit):
        '''Set the temperature limit above which control outputs assigned this channel
        shut off'''
        self.T_limit = limit
        resp = self.ls.msg(f'TLIMIT {self.input},{self.T_limit}')
        return resp

# Curve class copied from socs/Lakeshore372.py on 2020/08/21
class Curve:
    """Calibration Curve class for the LS336."""
    def __init__(self, ls, curve_num):
        self.ls = ls
        self.curve_num = curve_num
        self.get_header()  

    def get_header(self):
        """Get curve header description.
        :returns: response from CRVHDR? in list
        :rtype: list of str
        """
        resp = self.ls.msg(f"CRVHDR? {self.curve_num}").split(',')
        print(resp)

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
        assert _format.strip() in ['1', '2', '3', '4']
        _limit = params[3]
        _coeff = params[4]
        assert _coeff.strip() in ['1', '2']

        print(f'CRVHDR {_curve_num},{_name},{_sn},{_format},{_limit},{_coeff}')
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
                        "mV/K (linear)"
                        "V/K (linear)"
                        "Ohm/K (linear)"
                        "log Ohm/K (linear)"
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
        :param index: index of breakpoint to msg
        :type index: int
        :returns: (units, tempertaure, curvature) values for the given breakpoint
        :rtype: 3-tuple of floats
        """
        resp = self.ls.msg(f"CRVPT? {self.curve_num},{index}").split(',')
        _units = float(resp[0])
        _temp = float(resp[1])
        return (_units, _temp)

    def _set_data_point(self, index, units, kelvin):
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
        """Get a calibration curve from the LS336.
        If _file is not None, save to file location.
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
                f.write('Curve Name:\t' + self.name + '\r\n')
                f.write('Serial Number:\t' + self.serial_number + '\r\n')
                f.write('Data Format:\t' + format_lock[self.format] + f'\t({self.format})\r\n')
                f.write('SetPoint Limit:\t%s\t(Kelvin)\r\n' % '%0.4f' % np.max(self.breakpoints['temperature']))
                f.write('Temperature coefficient:\t' + tempco_lock[self.coefficient] + f' ({self.coefficient})\r\n')
                f.write('Number of Breakpoints:\t%s\r\n' % len(self.breakpoints))
                f.write('\r\n')
                f.write('No.\tUnits\tTemperature (K)\r\n')
                f.write('\r\n')
                for idx, point in enumerate(self.breakpoints):
                    f.write('%s\t%s %s\r\n' % (idx+1, '%0.5f' % point['units'], '%0.4f' % point['temperature']))

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

        # Skip to the V and T values in the file and strip them of tabs, newlines, etc
        values = []
        for i in range(9, len(content)):
            values.append(content[i].strip().split())

        self.delete_curve()  # remove old curve first, so old breakpoints don't remain
        time.sleep(1) # necessary to make work

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
    
        for j in range(1, len(values)+1):
            try:
                resp = self.get_data_point(j) #response from the 336
                point = values[j-1]
                units = float(resp[0])
                temperature = float(resp[1])
                assert units == float(point[1]), "Point number %s not uploaded"%point[0]
                assert temperature == float(point[2]), "Point number %s not uploaded"%point[0]
                print("Successfully uploaded %s, %s" %(units,temperature))
            #if AssertionError, tell 336 to re-upload points
            except AssertionError:
                if units != float(point[1]):
                    self.set_curve(_file)

    def delete_curve(self):
        """Delete the curve using the CRVDEL command.
        :returns: the response from the CRVDEL command
        :rtype: str
        """
        resp = self.ls.msg(f"CRVDEL {self.curve_num}")
        # self.get_header()
        return resp

    def soft_cal(self, std, points, delay = 1):
        '''Executes SCAL command using the data in points_str.
        Note this overmsgs the current breakpoints!

        Parameters
        ----------
        std : int
            Standard curve number to base the SoftCal on
        points : list
            List of T1,U1,T2,U2,T3,U3 values
        '''
        assert len(points) == 6
        points_str = ','.join(points)

        resp = self.ls.msg(f'SCAL {std},{self.curve_num},{self.serial_number},{points_str}', delay = delay)
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

# Heater class copied from socs/Lakeshore372.py on 2020/08/25
class Heater:

    def __init__(self, ls, output):
        """Heater class for LS336 control
        :param ls: the lakeshore object we're controlling
        :type ls: Lakeshore336.LS336
        :param output: the heater output we want to control, 1 = 100W, 2 = 50W
        :type output: int
        """
        assert int(output) in [1, 2] 

        self.ls = ls
        self.output = output
        self.output_name = f'Heater {output}'
        
        self.get_output_mode()
        self.get_heater_setup()
        self.get_heater_range()
        self.get_setpoint()

    def get_output_mode(self):
        """msg the heater mode using the OUTMODE? command.
        :returns: 3-tuple with output mode, input, and whether powerup is enabled
        :rtype: tuple
        """
        resp = self.ls.msg(f"OUTMODE? {self.output}").split(",")

        # TODO: make these human readable
        self.mode = output_modes_key[resp[0]]
        self.input = channel_key[resp[1]]
        self.powerup = resp[2]
        return resp

    # OUTMODE
    def _set_output_mode(self, params):
        """Set the output mode of the heater with the OUTMODE command.
        Parameters should be <mode>, <input>, and <powerup enable>.
        This allows us to use output from get_output_mode directly, as 
        it doesn't return <output>.
        :param params: OUTMODE parameters
        :type params: list of str
        :returns: response from ls.msg
        """
        assert len(params) == 3

        reply = [str(self.output)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        return self.ls.msg(f"OUTMODE {param_str}")

    def get_mode(self):
        """Set output mode with OUTMODE? commnd.
        :returns: The output mode
        :rtype: str
        """
        self.get_output_mode()
        return self.mode

    def set_mode(self, mode):
        """Set output mode with OUTMODE commnd.
        :param mode: control mode for heater
        :type mode: str
        :returns: the response from the OUTMODE command
        """
        assert mode.lower() in output_modes_lock.keys(), f"{mode} not a valid mode"

        resp = self.get_output_mode()
        resp[0] = output_modes_lock[mode.lower()]
        self.mode = mode
        return self._set_output_mode(resp)

    def get_input_channel(self):
        """Get the control channel with the OUTMODE? command.
        :returns: The control channel
        :rtype: str
        """
        self.get_output_mode()
        return self.input

    def set_input_channel(self, _input):
        """Set the control channel with the OUTMODE command.
        :param _input: specifies which input or channel to control from
        :type _input: str or int
        """
        assert _input in channel_lock, f"{_input} not a valid input/channel"

        resp = self.get_output_mode()
        resp[1] = channel_lock[str(_input)]
        self.input = str(_input)
        return self._set_output_mode(resp)

    def get_powerup(self):
        """Get the powerup state with the OUTMODE? command.
        :returns: The powerup state
        :rtype: str
        """
        self.get_output_mode()
        return self.powerup

    def set_powerup(self, powerup):
        """
        :param powerup: specifies whether the output remains on or shuts off
                        after power cycle. True for on after powerup
        :type powerup: bool
        """
        assert powerup in [True, False], f"{powerup} not valid powerup parameter"
    
        resp = self.get_output_mode()
        set_powerup = str(int(powerup))
        resp[2] = set_powerup
        self.powerup = set_powerup
        return self._set_output_mode(resp)
    
    def get_heater_setup(self):
        """Gets Heater setup params with the HTRSET? command.
        :return resp: List of values that have been returned from the Lakeshore.
        """
        resp = self.ls.msg("HTRSET? {}".format(self.output)).split(',')

        self.resistance_setting = int(resp[0])
        self.max_current = max_current_key[resp[1]]
        self.max_user_current = float(resp[2].strip('E+'))
        self.display = heater_display_key[resp[3]]

        return resp

    def _set_heater_setup(self, params):
        """
        Sets the heater setup using the HTRSET command.
        Params must be a list with the parameters:
            <heater resistance mode>:    Heater mode in Ohms; 1=25 Ohms, 2=50 Ohms
            <max current>: Specifies max heater output for warm-up heater.
                           0=User spec, 1=0.707 A, 2=1 A, 3=1.141 A, 4=2 A.
            <max user current>: Max heater output if max_current is set to user
            <current/power>:    Specifies if heater display is current or power.
                                1=current, 2=power.
        :param params:
        :return:
        """
        assert len(params) == 4

        reply = [str(self.output)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        return self.ls.msg("HTRSET {}".format(param_str))

    def get_heater_resistance_setting(self):
        '''Get the "setting" of the heater resistance, which can only be 25 or 50 Ohms
        '''
        self.get_heater_setup()
        return self.resistance_setting

    def set_heater_resistance(self, res):
        '''Sets the correct heater setting depending on the actual load resistance

        Parameters
        ----------
        res : int or float
            Actual resistance of load being powered
        '''
        if res < 50: setting = 1  # 25 Ohm
        elif res >= 50: setting = 2 # 50 Ohm
        self.resistance = res

        resp = self.get_heater_setup()
        resp[0] = str(setting)
        self.resistance_setting = setting
        return self._set_heater_setup(resp)

    def get_max_current(self):
        '''Get the limiting current of the heater. Either set by "max current"
        if user max current not on, or user max current if user max current on.

        Returns
        -------
        float
            Limiting heater current
        '''
        self.get_heater_setup()
        if self.max_current == 'User': return self.max_user_current
        else: return self.max_current

    def set_max_current(self, current):
        assert current <= 2, f'Current {current} is too high (>2 A)'
        current = math.floor(1000*current)/1000 #round down to 3 decimal places

        resp = self.get_heater_setup()
        if current in max_current_lock:
            resp[1] = str(current)
            self.max_current = current
        else: 
            resp[1] = '0'
            self.max_current = 'User'
            resp[2] = str(current)
            self.max_user_current = current
        return self._set_heater_setup(resp)

    def get_heater_display(self):
        '''Get whether heater displays in % of full current or power

        Returns
        -------
        str
            Display unit (% of current or % of power)
        '''
        self.get_heater_setup()
        return self.display

    def set_heater_display(self, display):
        """Change the display of the heater 
        :param display: Display mode for heater. Can either be 'current' or 'power'.
        :type display: string
        """
        assert display.lower() in heater_display_lock.keys(), f"{display} is not a valid display"

        resp = self.get_heater_setup()
        resp[3] = heater_display_lock[display.lower()]
        self.display = display
        return self._set_heater_setup(resp)

    def get_manual_out(self):
        '''Return the % of full current or power depending on heater display, if set by MOUT

        Returns
        -------
        float
            the % of full current or power depending on heater display
        '''
        resp = self.ls.msg("MOUT? {}".format(self.output))
        return float(resp)

    def set_manual_out(self, percent):
        '''Set the % of full current or power depending on heater display, with MOUT

        Parameters
        ----------
        percent : int or float
            the % of full current or power depending on heater display
        '''
        assert 100*percent == int(100*percent), "Percent value cannot have more than 2 decimal places"

        resp = self.ls.msg(f'MOUT {self.output},{percent}')
        return resp

    def get_heater_range(self):
        """Get heater range with RANGE? command.
        :returns: heater range by decade in total available power/current
        :rtype: float
        """
        resp = self.ls.msg(f"RANGE? {self.output}")
        self.range = heater_range_key[resp]
        return self.range

    def set_heater_range(self, _range):
        """Set heater range with RANGE command.
        :param _range: heater range
        :type _range: str in 'Off','Low','Medium','High'
        """
        _range = _range.lower()
        assert _range in heater_range_lock.keys(), 'Not a valid heater Range'

        self.range = heater_range_lock[_range]
        resp = self.ls.msg(f"RANGE {self.output},{heater_range_lock[_range]}")
        return resp

    def get_setpoint(self):
        '''Return the setpoint in control loop sensor units'''
        resp = self.ls.msg(f"SETP? {self.output}")
        self.setpoint = resp
        return self.setpoint

    def set_setpoint(self, value):
        '''Set the setpoint of the control loop in sensor units 

        Parameters
        ----------
        value : int or float
            The setpoint. Units depend on the preferred sensor units.
        '''
        self.setpoint = value
        resp = self.ls.msg(f"SETP {self.output},{value}")
        return resp

    def get_pid(self):
        """Get PID parameters with PID? command.
        :returns: P, I, D
        :rtype: float, float, float
        """
        resp = self.ls.msg(f"PID? {self.output}").split(',')
        self.P = float(resp[0])
        self.I = float(resp[1])
        self.D = float(resp[2])
        return self.P, self.I, self.D

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
        assert float(P) <= 1000 and float(P) >= 0.1
        assert float(I) <= 1000 and float(I) >= 0.1
        assert float(D) <= 200 and float(D) >= 0

        self.P = P
        self.I = I
        self.D = D

        resp = self.ls.msg(f"PID {self.output},{P},{I},{D}")
        return resp

    def get_ramp(self):
        '''Return list of params <on/off>, <rate value> for RAMP? msg

        Returns
        -------
        list
            <on/off>, <rate value> for RAMP? msg
        '''
        resp = self.ls.msg(f'RAMP? {self.output}').split(',')
        self.ramp_enabled = ramp_key[resp[0]]
        self.ramp_rate = float(resp[1])
        return resp

    def _set_ramp(self, params):
        '''Set the RAMP params <on/off>, <rate value>

        Parameters
        ----------
        params : list
            <on/off>, <rate value>
        '''
        assert len(params) == 2

        reply = [str(self.output)]
        [reply.append(x) for x in params]

        param_str = ','.join(reply)
        resp = self.ls.msg(f'RAMP {param_str}')
        return resp

    def get_ramp_on_off(self):
        '''Get string indicating ramp 'on' or 'off' '''
        self.get_ramp()
        return self.ramp_enabled

    def set_ramp_on_off(self, on_off):
        '''Turn ramp on or off

        Parameters
        ----------
        on_off : str
            Either 'on' to enable ramp or 'off' to disable ramp
        '''
        assert on_off.lower() in ramp_lock

        resp = self.get_ramp()
        resp[0] = ramp_lock[on_off.lower()]
        self.ramp_enabled = on_off.lower()
        return self._set_ramp(resp)

    def get_ramp_rate(self):
        '''Returns ramp rate in K/min'''
        self.get_ramp()
        return self.ramp_rate

    def set_ramp_rate(self, rate):
        '''Set ramp rate of changes in setpoint, in K/min

        Parameters
        ----------
        rate : int or float
            Absolute value of setpoint rate of change, from 0.1 to 100 K/min
        '''
        assert rate >= 0.1 and rate <= 100

        resp = self.get_ramp()
        resp[1] = str(rate)
        self.ramp_rate = rate
        return self._set_ramp(resp)

    def get_ramp_status(self):
        '''Return a string indicating whether or not the setpoint
        is currently ramping'''
        resp = self.ls.msg(f'RAMPST? {self.output}')
        ramp_stat_dict = {'0': 'Not ramping', '1': 'Ramping'}
        self.ramp_status = ramp_stat_dict[resp]
        return self.ramp_status

    def get_heater_percent(self):
        '''Return the current heater output level in %'''
        resp = self.ls.msg(f'HTR? {self.output}')
        self.percent = float(resp)
        return self.percent

# Do stuff

if __name__ == '__main__':

    # Initialize device

    box = LS336('/dev/ttyUSB0')

    # Ask basic questions
    
    print('Comm Active:', box.comm.is_open)
    print(box.msg('*IDN?'))
    print(box.get_kelvin('0'))
    box.comm.close()
    print('Comm Active:', box.comm.is_open)
