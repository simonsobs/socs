import time
import math
import select
import serial
import yaml

from socs.tcp import TCPInterface

countspermm = 4000
countsperdeg = 2000
maxspeed = 100000


#brake_output_map = {'A': 1, 'B': 2, 'C': 3, 'D': 4}

#axes = ['A', 'B', 'C', 'D']

axes = ['E', 'F']

brake_output_map = {'E': 5, 'F': 6}

countspermm = 4000
countsperdeg = 2000

class GalilAxis(TCPInterface):
    def __init__(self, ip, configfile, port=23, timeout=10):
        """Interface class for connecting to GalilStageController for SO SAT Coupling Optics."""
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.configfile = configfile

        super().__init__(self.ip, self.port, self.timeout)
    
    def _drain_prompt(self):
        """Drain the TCP buffer until no more data or a Galil ':' prompt is seen."""
        start = time.time()
        drained = b""

        while True:
            # Non-blocking check for available data
            rlist, _, _ = select.select([self.comm], [], [], 0.05)
            if not rlist:
                break

            chunk = self.recv(256)
            if not chunk:
                break

            drained += chunk

            # If we see a prompt (:) at the end or within the buffer, assume done
            if drained.endswith(b"\r:") or b":" in drained:
                break

            # Safety stop to avoid infinite loop
            if time.time() - start > 0.3:
                break

        # Optional: uncomment for debugging only
        # if drained:
        #     print(f"[drained] {drained!r}")
        return drained

    def galil_command(self, command=None, axis=None, value=None, timeout=3.0, max_retries=4, expect_response=False):
        """
        Send a Galil command via TCP and read until ':' prompt appears.
        Handles empty ('') and '??' responses by draining the leftover ':' prompt
        before retrying.
        """

        # --- Build command string ---
        if axis is not None and value is not None:
            cmd = f"{command}{axis} = {value}"
        elif axis is not None:
            cmd = f"{command}{axis}"
        elif command and value:
            cmd = f"{command} = {value}"
        else:
            cmd = f"{command}"
        msg = f"{cmd}\r".encode("ascii")

        for attempt in range(max_retries):
            self._drain_prompt()        # actively clear leftover ':' or partial echoes
            self.send(msg)

            resp = b""
            start = time.time()
            while True:
                rlist, _, _ = select.select([self.comm], [], [], 0.05)
                if rlist:
                    chunk = self.recv(256)
                    if not chunk:
                        time.sleep(0.01)
                        continue
                    resp += chunk
                    if b":" in resp:
                        break
                if time.time() - start > timeout:
                    print(f"Timeout waiting for ':' after '{cmd}' (attempt {attempt+1})")
                    break
                time.sleep(0.01)

            decoded = resp.decode("ascii", errors="ignore").strip(":\r\n ")
            
            if not expect_response:
                # verify that ':' or a "" was seen in the raw response, particularly for cases of sending commands that are not queries
                if b":" or resp == b"":
                    print(f'{cmd} acknowledged')
                else:
                    print(f"No ':' prompt seen for '{cmd}', command may not have completed.")

            # --- Retry logic for '?', '??', or '' ---
            if decoded in ("", "?", "??"):
                print(f"Got '{decoded}' from Galil, draining & retrying, attempt ({attempt+1}/{max_retries})...")
                self._drain_prompt()
                time.sleep(0.1)
                continue

            try:
                val = float(decoded)
                return val
            except Exception as e:
                return f"Exception occured with format of response: {decoded}"

        return None


    def get_relative_position(self, axis, movetype=None):
        """
        Query the relative position set for a specified axis using galil_command.
        Converts counts to physical units if movetype is 'linear' or 'angular'.
        """
        units_map = {'linear': 'mm', 'angular': 'deg'}
        units = units_map.get(movetype, '')

        # --- Query the controller using robust galil_command() ---
        value = self.galil_command("MG _PR", axis)

        # --- If we got a bad response, exit gracefully ---
        if value is None or isinstance(value, str):
            print(f"⚠️ Invalid response for _PR{axis}: {value}")
            return math.nan, units

        # --- Convert from counts to units if known ---
        try:
            if movetype == 'linear':
                value /= self.countspermm
            elif movetype == 'angular':
                value /= self.countsperdeg
        except AttributeError:
            print("countspermm / countsperdeg not defined on this class.")
        except Exception as e:
            print(f"Error converting units: {e}")

        return value, units
 

    def get_data(self):
        """
        Query position (_TP), velocity (_TV), and torque (_TT)
        for each active Galil axis using the robust galil_command().
        Returns a dict ready for OCS publication.
        """
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}") 

        data = {}
        axes = list(config['galil']['motorconfigparams'].keys())

        for axis in axes:
            axis_data = {}

            # --- Position ---
            pos = self.galil_command("MG _TP", axis, expect_response=True)
            if pos is None or isinstance(pos, str) and pos in ("", "?", "??"):
                pos = math.nan
            axis_data["position"] = pos

            # --- Velocity ---
            vel = self.galil_command("MG _TV", axis, expect_response=True)
            if vel is None or isinstance(vel, str) and vel in ("", "?", "??"):
                vel = math.nan
            axis_data["velocity"] = vel

            # --- Torque ---
            trq = self.galil_command("MG _TT", axis, expect_response=True)
            if trq is None or isinstance(trq, str) and trq in ("", "?", "??"):
                trq = math.nan
            axis_data["torque"] = trq
        
            # --- Position Error ---
            poserr = self.galil_command("MG _TE", axis, expect_response=True)
            if poserr is None or isinstance(poserr, str) and trq in ("", "?", "??"):
                poserr = math.nan
            axis_data["position_error"] = poserr
            
            # --- Gearing Ratio ---
            gr = self.galil_command("MG _GR", axis, expect_response=True)
            if gr is None or isinstance(gr, str) and trq in ("", "?", "??"):
                gr = math.nan
            axis_data["gearing_ratio"] = gr

            data[axis] = axis_data

            # delay between axes querying
            time.sleep(0.1)

        return data


    def begin_motion(self, axis):
        """Begin motion for the specified axis using the BG command."""
        self.galil_command(command="BG", axis=axis)


    def set_relative_linearpos(self, axis, lindist):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts.
        axis (str), lindist = int/float in mm units"""
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}")
        try:
            countspermm = config['galil']['motorsettings']['countspermm']
        except Exception as e:
            print(f'Exception occured: {e}')

        counts = round(lindist * countspermm, 3)
        resp = self.galil_command(command="PR", axis=axis, value=counts)

        return resp


    def set_absolute_linearpos(self, axis, pos):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts.
        axis (str), pos = int/float; the actual position you want it to go to"""
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}")
        try:
            countspermm = config['galil']['motorsettings']['countspermm']
        except Exception as e:
            print(f'Exception occured: {e}')

        counts = round(pos * countspermm, 3)
        resp = self.galil_command(command="PA", axis=axis, value=counts)

        return resp


    def set_relative_angularpos(self, axis, angdist):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts.
        axis (str), angdist = int/float in degree units"""
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}")
        
        try:
            countsperdeg = config['galil']['motorsettings']['countsperdeg']
        except Exception as e:
            print(f'Exception occured: {e}')

        counts = round(angdist * countsperdeg, 3)
        resp = self.galil_command(command="PR", axis=axis, value=counts)

        return resp


    def set_absolute_angularpos(self, axis, pos):
        """Move all linear axes by a given distance in mm, which is converted
        into encoder counts.
        axis (str), pos  = int/float; the angular position you actually wanna go to"""
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}")

        try:
            countsperdeg = config['galil']['motorsettings']['countsperdeg']
        except Exception as e:
            print(f'Exception occured: {e}')

        counts = round(pos * countsperdeg, 3)
        resp = self.galil_command(command="PA", axis=axis, value=counts)

        return resp


    def release_brake(self, axis):
        """Release brake to axis by using the GalilDMC SB command which sets the digital
        output to 1 which somehow means it releases the brake. Galil command expects an int
        for digital output number"""
        try:
            digital_output = self.configfile['galil']['brakes']['output_map'][axis]
        except Exception as e:
            print(f'Exception occured: {e}')
        resp = self.galil_command(command="SB", value=brake_output)
        return resp

    
    def engage_brake(self, axis):
        """ Engage the brake for the specified axis using the Galil CB command.
        Reads the brake output mapping from the config file (under galil.brakes.output_map)."""
        try:
            digital_output = self.configfile['galil']['brakes']['output_map'][axis]
        except Exception as e:
            print(f'Exception occured: {e}')
        resp = self.galil_command(command="CB", value=brake_output)
        return resp


    def get_brake_status(self, axis=None):
        """
        Query brake status for one or all axes using @OUT[n].
        Reads brake output mapping from galil.brakes.output_map in the config file.
        If axis is specified, only that brake is queried.
        """
        if isinstance(self.configfile, str):
            try:
                with open(self.configfile, "r") as f:
                    config = yaml.safe_load(f)
            except Exception as e:
                raise RuntimeError(f"Failed to load config file '{self.configfile}': {e}")

        brake_states = {}

        output_map = config['galil']['brakes']['output_map']

        # If a specific axis was given, limit to that one
        if axis:
            output_map = {axis: output_map.get(axis)}

        for label, output_num in output_map.items():
            # the digital output string for querying brake status: MG @OUT[n]
            query_str = f"@OUT[{output_num}]"
            val = self.galil_command(command="MG", value=query_str)

            try:
                num_val = float(val)
                state = int(round(num_val))
            except (TypeError, ValueError):
                print(f"Could not parse brake value '{val}' for axis {label}.")
                brake_states[label] = {"state": None, "status": "Unknown"}
                continue

            if state == 1:
                status = "Brake Released"
            elif state == 0:
                status = "Brake Engaged"

            brake_states[label] = {"state": state, "status": status}

        return brake_states


    def set_motor_type(self, axis, type=1):
        """set the motor type for each axis. defaults to 1, the servo motor (3-phased brushless)"""
        resp = self.galil_command(command=f'MT{axis}={type};')
        return resp


    def disable_off_on_error(self, axis):
        """Disables the Off-On-Error (OE) function for the specified axis, preventing the controller from shutting off motor commands in response to position errors."""
        resp = self.galil_command(command=f'OE{axis}=0;')
        return resp

    def set_amp_gain(self, axis, val=2):
        """ set amplifier current/voltage gain for internal amplifier per axis. Default is 2"""
        resp = self.galil_command(command=f'AG{axis}={val};')
        return resp


    def set_torque_limit(self, axis, val=5):
        """ set motor torque limit per axis. Default is 5."""
        resp = self.galil_command(command=f'TL{axis}={val};')
        return resp


    def set_amp_currentloop_gain(self, axis, val=9):
        """ set amplifier current loop gain per axis. Default is 9."""
        resp = self.galil_command(command=f'AU{axis}={val};')
        return resp

    # init
    def enable_sin_commutation(self, axis):
        """ for axes with a sinusoidal amplifier, the BA command is necessary to configure each axis for sinusoidal commutation"""
        resp = self.galil_command(command=f'BA{axis};')
        return resp

    # init
    def set_magnetic_cycle(self, axis, val='3276.8'):
        """defines the length of the motors magnetic cycle in encoder counts, required for correctly configuring sinusoidal commutation. Default is 3276.8"""
        resp = self.galil_command(command=f'BM{axis}={val};')
        return resp

    # init    
    def initialize_axis(self, axis, val=3):
        """initializes axes configured for sinusoidal commutation. BZ command will drive the motor to 2 different magnetic positions and then set the appropriate commutation angel. Cannot command with BZ unless BA and BM commands are sent first. Default value is 3 volts."""
        resp = self.galil_command(command=f'BZ{axis}={val};')
        return resp

    # home
    def define_position(self, axes, val=0):
        # Part of the homing process which requires jogging to the reverse limit switch and then defining the position of the axis at that limit as 0"""
        resp = self.galil_command(command=f'DP{axis}={val};')
        return resp


    def disable_limit_switch(self, axis):
        """Disable limit switch detection on a given axis (LDx=3)."""
        resp = self.galil_command(command=f'LD{axis}=3;', expect_response=True)
        return resp


    def set_limitswitch_polarity(self, pol=1):
        """CN -1 means active low, CN +1 is active high. And we want active high"""
        resp = self.galil_command(command=f'CN {pol};')
        return resp


    def stop_motion(self, axis=None):
        """Stop motion. If axis is None, stop all."""
        cmd = "ST;" if axis is None else f"ST {axis};"
        resp = self.galil_command(command=cmd)
        return resp


    def set_gearing(self, order):
        """Set gearing: order is order of opertions in string: ',A,,C'."""
        resp = self.galil_command(command=f"GA {order};")
        return resp


    def set_gearing_ratio(self, order):
        """Set gearing ratios, e.g. GR -1,1 for axes B and D."""
        resp = self.galil_command(command=f"GR {order};")
        return resp


    def jog_axis(self, axis, speed):
        """Set jog speed for axis and begin jogging."""
        cmd = f"JG{axis}={speed};"
        resp = self.galil_command(command=cmd)
        return resp


    def begin_axis_motion(self, axis):
        """Set jog speed for axis and begin jogging."""
        resp = self.galil_command(command=f"BG{axis}")
        return resp


    def enable_axis(self, axis=None):
        """Enable servo for an axis (e.g. A, B, C, D)."""
        cmd = f'{SH}{axis};'
        resp = self.galil_command(command=cmd)
        return resp


    def disable_axis(self, axis):
        """Motor off for an axis."""
        resp = self.galil_command(command=f"MO{axis}")
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


    def get_position(self, axis):
        """Query position of an axis."""
        cmd = f"TP {axis}"
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


    def flip_limitswitch_polarity(self, pol=1):
        """CN -1 means active low, CN +1 is active high. And we want active high"""
        cmd = f"CN {pol}"
        return self.send_command(cmd)

    '''
