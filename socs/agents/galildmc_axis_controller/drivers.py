import time

import serial
import yaml

from socs.tcp import TCPInterface

countspermm = 4000
countsperdeg = 2000
maxspeed = 100000


brake_output_map = {'A': 1, 'B': 2, 'C': 3, 'D': 4}


class GalilAxis(TCPInterface):
    def __init__(self, ip, port=23, timeout=10):
        """Interface class for connecting to GalilStageController for SO SAT Coupling Optics."""
        self.ip = ip
        self.port = port
        self.timeout = timeout

        super().__init__(self.ip, self.port, self.timeout)

    def query(self, expr):
        """Send MG query and return decoded response string."""
        msg = f"MG {expr}\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp.strip(": \r\n")

    def query_relative_position(self, axis, movetype=None):
        """Query relative position set for a specified axis"""

        units_map = {'linear': 'mm', 'angular': 'deg'}
        units = units_map.get(movetype, '')

        self.query(f'_PR{axis}')
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore").strip(": \r\n")

        try:
            value = float(resp)
        except ValueError as e:
            print(f'Raised exception {e}, value type not a number.')
            value = None

        if movetype == 'linear':
            value /= countspermm
        elif movetype == 'angular':
            value /= countsperdeg

        return value, units

    def get_data(self):
        """
        Gets the position, velocity, and torque data from the galil stage motor and returns in a usable format.
        """
        axes = ['A', 'B', 'C', 'D']
        data = {}

        for axis in axes:
            try:
                pos = float(self.query(f"_TP{axis}").strip(": \r\n"))
                vel = float(self.query(f"_TV{axis}").strip(": \r\n"))
                trq = float(self.query(f"_TT{axis}").strip(": \r\n"))
            except (ValueError, AttributeError):
                pos, vel, trq = float("nan"), float("nan"), float("nan")
                self.log.warning(f"Invalid response while querying axis {axis}")

            data[axis] = {"position": pos, "velocity": vel, "torque": trq, }

        return data

    def set_linear(self, axis, lindist):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts."""

        msg = f"PR{a}={lindist*countspermm:.0f};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def begin_motion(self, axis):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts to communicate to the galil axis controller."""

        msg = f"BG{axis};".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def set_angular(self, axis, angdist):
        """Move all angular axes by a given distance in degrees, which is converted
        into encoder counts."""

        msg = f"PR{axis}={angdist*countsperdeg:.0f};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def release_brake(self, axis):
        """Release brake to axis by using the GalilDMC SB command which sets the digital
        output to 1 which somehow means it releases the brake. Galil command expects an int
        for digital output number"""
        digital_output = brake_output_map[axis]
        msg = f"SB{digital_output};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def engage_brake(self, axis):
        """Release brake to axis by using the GalilDMC SB command which clears the digital
        output bit which somehow engages the brake. Galil command expects an int
        for digital output number"""
        digital_output = brake_output_map[axis]
        msg = f"CB{digital_output};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def query_brake_status(self):
        """query brake status for both linear and angular axes"""
        axes = list(brake_output_map)

        brake_states = {}
        for label, i in brake_output_map.items():
            # query will return 0 or 1 float
            val = self.query(f'@OUT[{i}]')

            try:
                num_val = float(val)
                state = int(round(num_val))
                brake_states[label] = state
            except ValueError:
                print(f"Could not parse brake value '{val}' for axis {label}")

            if state == 1:
                status = "Brake Released"
            elif state == 0:  
                status = "Brake Engaged"

            brake_states[label] = {"state": state, "status": status}

        return brake_states

    def set_motor_type(self, axis, type=1):
        """set the motor type for each axis. defaults to 1, the servo motor (3-phased brushless)"""
         msg = f"MT{axis}={type};\r".encode("ascii")
         self.send(msg)
         resp = self.recv(4096).decode("ascii", errors="ignore")
         return resp


    def disable_off_on_error(self, axis):
        """Disables the Off-On-Error (OE) function for the specified axis, preventing the controller from shutting off motor commands in response to position errors."""
         msg = f"OE{axis}={0};\r".encode("ascii")
         self.send(msg)
         resp = self.recv(4096).decode("ascii", errors="ignore")
         return resp

    def set_amp_gain(self, axis, val=2):
        """ set amplifier current/voltage gain for internal amplifier per axis. Default is 2"""

        msg = f"AG{axis}={val};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp


    def set_torque_limit(self, axis, val=5):
        """ set motor torque limit per axis. Default is 5."""
        msg = f"TL{axis}={val};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp


    def set_amp_currentloop_gain(self, axis, val=9):
        """ set amplifier current loop gain per axis. Default is 9."""
        msg = f"AU{axis}={val};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp

    # init
    def enable_sin_commutation(self, axis):
        """ for axes with a sinusoidal amplifier, the BA command is necessary to configure each axis for sinusoidal commutation"""
        msg = f"BA{axis};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp

    # init
    def set_magnetic_cycle(self, axis, val='3276.8'):
        """defines the length of the motors magnetic cycle in encoder counts, required for correctly configuring sinusoidal commutation. Default is 3276.8"""
        msg = f"BM{axis}={val};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp

    
    def initialize_axis(self, axis):
        """initializes axes configured for sinusoidal commutation. BZ command will drive the motor to 2 different magnetic positions and then set the appropriate commutation angel. Cannot command with BZ unless BA and BM commands are sent first."""
        msg = f"BZ{axis};\r".encode("ascii")
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")
        return resp


    def home(self, axes):
        # TODO: homing logic
        # TODO: when moving using a `goto` function, some conditions to make sure it's homed
        # or it won't move; specifically check for gearing ratio
        # can set scripts such that galil will start the script automatically on startup for
        # comparing A and B axes TPA and if offset, shut motor off
        """Send homing sequence for all axes (example)."""
        msg = f"HM{a};"
        self.send(msg)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp

    def command_rawsignal(self, command=None, axis=None, value=None):
        "for just getting some commands with raw functions"
        if axis is not None:
            cmd = f'{command}{axis}'
        if axis is not None and value is not None:
            cmd = f'{command}{axis} = {value}'
        elif command and value:
            cmd = f'{command} = {value}'
        else:
            cmd = f'{command}'

        self.send_(cmd)
        resp = self.recv(4096).decode("ascii", errors="ignore")

        return resp


    '''
    def command_config(self):
        """Send all relevant Galil config commands from loaded TOML."""
        # 1. Global confcomm
        confcomm = self.config.get('confcomm', "").strip()
        if confcomm:
            print(f"Sending confcomm: {confcomm}")
            self.send_command(confcomm)

        print('in command_config method, sleeping for 2 sec')
        time.sleep(2)

        # 2. Per-axis init commands
        #for axis in ['A', 'B', 'C', 'D']:
        #    self.initialize_axis(axis)
        #    print(f"Initialized axis {axis}, sleeping for 2 secs...")
        #    time.sleep(5)

        # 3. Optional maxspeed
        if 'maxspeed' in self.config:
            maxspeed = self.config['maxspeed']
            comm = ''
            for a in self.config.get('linaxis', '').split():
                comm += f"SP{a}={maxspeed};"
            for a in self.config.get('angaxis', '').split():
                comm += f"SP{a}={maxspeed};"
            if comm:
                comm = comm.rstrip(';')  # trim trailing semicolon
                print(f"Setting maxspeed: {comm}")
                self.send_command(comm)

    def initialize_axis(self, axis, volts=3):
        """Use BZ command to initialize axis."""
        cmd = f"BZ{axis}={volts}"
        return self.send_command(cmd)

    # ---- Convenience wrappers ----
    def move_absolute(self, axis, pos):
        """Move an axis to an absolute position (pos in encoder counts or units)."""
        cmd = f"PA {axis}={pos};BG {axis}"
        return self.send_command(cmd)

    def move_relative(self, axis, delta):
        """Move an axis by delta relative units."""
        cmd = f"PR {axis}={delta};BG {axis}"
        return self.send_command(cmd)

    def home_axis(self, axis):
        """Home an axis."""
        cmd = f"HM {axis}"
        return self.send_command(cmd)

    def stop(self, axis=None):
        """Stop motion. If axis is None, stop all."""
        cmd = "ST" if axis is None else f"ST {axis}"
        return self.send_command(cmd)

    def get_position(self, axis):
        """Query position of an axis."""
        cmd = f"TP {axis}"
        return self.send_command(cmd)

    def enable_axis(self, axis=None):
        """Enable servo for an axis (e.g. A, B, C, D)."""
        if axis is None:
            cmd = 'SH'
        else:
            cmd = f'{SH}{axis}'
        return self.send_command(cmd)

    def disable_axis(self, axis):
        """Motor off for an axis."""
        return self.send_command(f"MO{axis}")

    def set_gearing(self, lead, follow):
        """Set gearing: lead axis drives follow axis."""
        return self.send_command(f"GA {lead},{follow}")

    def set_gearing_ratio(self, *ratios):
        """Set gearing ratios, e.g. GR -1,1 for axes B and D."""
        args = ",".join(str(r) for r in ratios)
        return self.send_command(f"GR {args}")

    def jog_axis(self, axis, speed):
        """Set jog speed for axis and begin jogging."""
        cmd = f"JG{axis}={speed}"
        return self.send_command(cmd)

    def query_status(self, code):
        """Send MG query, e.g. query_status('_MOA')."""
        return self.send_command(f"MG {code}")

    def change_gain(self, axis, gain):
        """Change gain of axis."""
        cmd = f"AG{axis}={gain}"
        return self.send_command(cmd)

    def query_param(self, code):
        """Send a generic MG query and return the value."""
        return self.send_command(f"MG {code}")

    def disable_limit_switch(self, axis):
        """Disable limit switch detection on a given axis (LDx=3)."""
        cmd = f"LD{axis}=3"
        return self.send_command(cmd)

    def flip_limitswitch_polarity(self, pol=1):
        """CN -1 means active low, CN +1 is active high. And we want active high"""
        cmd = f"CN {pol}"
        return self.send_command(cmd)

    def command_rawsignal(self, command=None, axis=None, value=None):
        "for just getting some commands with raw functions"
        if axis is not None:
            cmd = f'{command}{axis}'
        if axis is not None and value is not None:
            cmd =  f'{command}{axis} = {value}'
        elif command and value:
            cmd = f'{command} = {value}'
        else:
            cmd = f'{command}'
        return self.send_command(cmd)

    def begin_axis_motion(self, axis):
        """Set jog speed for axis and begin jogging."""
        cmd = f"BG{axis}"
        return self.send_command(cmd)
    '''
