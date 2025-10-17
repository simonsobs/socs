import time
import math
import select
import serial
import yaml

from socs.tcp import TCPInterface

# TODO: set speed
# TODO: ask shreya about homing procedure; have the methods but don't have a full fledged
# homing method---do we need one?
# TODO: change prints to logs?
# TODO use the _safe_float method that was just written


class GalilAxis(TCPInterface):
    def __init__(self, ip, port=23, configfile=None, timeout=10):
        """Interface class for connecting to GalilStageController for SO SAT Coupling Optics."""
        self.ip = ip
        self.port = port
        self.configfile = configfile
        self.timeout = timeout

        super().__init__(self.ip, self.port, self.timeout)

    def _safe_float(self, val):
        """Convert Galil return string to float or NaN on error/'?'/empty."""
        if val is None:
            return math.nan
        if isinstance(val, str):
            s = val.strip()
            if s in ("", "?", "??"):
                return math.nan
            try:
                return float(s)
            except Exception:
                return math.nan
        try:
            return float(val)
        except Exception:
            return math.nan

    def _drain_prompt(self):
        """
        Drain the TCP buffer until a Galil ':' prompt is seen or timeout occurs.
        If a '?' is detected, query TC1 for an error code.
        Handles 'Input buffer full' (TC1=5) by pausing and waiting for the controller
        to clear before allowing new commands.
        """
        start = time.time()
        drained = b""
        received_any = False

        while True:
            rlist, _, _ = select.select([self.comm], [], [], 1)
            if rlist:
                chunk = self.recv()
            else:
                break

            if not chunk:
                break

            received_any = True
            drained += chunk

            if drained.endswith(b"\r:") or b":" in drained:
                break

            if time.time() - start > 3:
                break

        if received_any:
            decoded = drained.decode("ascii", errors="ignore").strip(":\r\n ")

            # --- ambiguous or empty response handling ---
            if decoded in ("?", "??"):
                print(f"Error response'{decoded}' — checking TC1 status...")

                self.send(b"TC1\r")
                time.sleep(0.100)

                tc_resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n ")

                if tc_resp.startswith("5"):
                    print("TC1=5 (Input buffer full) — clearing input buffer")
                    time.sleep(0.100)
                    self.send(b"CI -1;\r")
                else:
                    print('TC error response not 0 nor 5', tc_resp)
                return tc_resp

    def galil_command(self, command=None, axis=None, value=None,
                      timeout=3.0, expect_response=False):
        """
        Builds and transmits the command string, handles '?' retries for transient
        errors, and converts numeric responses to floats when possible.
        Motion-starting commands (BG) skip retries, as '?' responses are expected
        during active motion.

        """
        if axis is not None and value is not None:
            cmd = f"{command}{axis} = {value}"
        elif axis is not None:
            cmd = f"{command}{axis}"
        elif command and value:
            cmd = f"{command} = {value}"
        else:
            cmd = f"{command}"

        msg = f"{cmd}\r".encode("ascii")

        self._drain_prompt()  # clear any old data
        time.sleep(0.300)
        self.send(msg)
        resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n")

        # if we get a '?', handle it right away, unless it's a begin motion command;
        # we expect a '?' to occur mid-motion
        if 'MG' not in cmd:
            self._drain_prompt()
            time.sleep(0.3)
            self.send(msg)
            resp = ''
        else:
            for attempt in range(3):
                if '?' or '??' in resp:
                    #print(f"Received {resp} — retrying ({attempt+1}/3)...")
                    self._drain_prompt()
                    time.sleep(0.3)
                    self.send(msg)
                    resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n")
                else:
                    break

        #try:
        #    return float(resp)
        #except Exception as e:
        #    print(f'Exception {e} occurred. response is not a float: {resp}')
        return resp

    def get_relative_position(self, axis, movetype=None):
        """
        Query the relative position set for a specified axis using galil_command.
        Converts counts to physical units if movetype is 'linear' or 'angular'.
        """
        units_map = {'linear': 'mm', 'angular': 'deg'}
        units = units_map.get(movetype, '')

        # --- Query the controller using robust galil_command() ---
        value = self.galil_command("MG _PR", axis)
        try:
            value = float(value)
        except Exception as e:
            print(f'Exception occurred, returning nana: {e}')
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

    # TODO: add ability to publish encoder units in values of mm and degs
    def get_data(self, axes):
        """
        Query position (_TP), velocity (_TV), and torque (_TT)
        for each active Galil axis using the robust galil_command().
        Returns a dict ready for OCS publication.
        axes is list of axes like ['A', 'B', 'C']
        """
        if not axes or not isinstance(axes, list):
            raise ValueError("get_data() requires a list of axes from agent (e.g. ['E','F']).")

        data = {}

        for axis in axes:
            axis_data = {}

            # --- Position ---
            pos = self.galil_command("MG _TP", axis, expect_response=True)
            if pos is None or pos in ('?', '??', ''):
                pos = math.nan
            else:
                pos = float(pos)
            axis_data["position"] = pos

            # --- Velocity ---
            vel = self.galil_command("MG _TV", axis, expect_response=True)
            if vel is None or vel in ('?', '??', ''):
                vel = math.nan
            else:
                vel = float(vel)
            axis_data["velocity"] = vel

            # --- Torque ---
            trq = self.galil_command("MG _TT", axis, expect_response=True)
            if trq is None or trq in ('?', '??', ''):
                trq = math.nan
            else:
                trq = float(trq)
            axis_data["torque"] = trq

            # --- Position Error ---
            poserr = self.galil_command("MG _TE", axis, expect_response=True)
            if poserr is None or poserr in ('?', '??', ''):
                poserr = math.nan
            else:
                poserr = float(poserr)
            axis_data["position_error"] = poserr

            # --- Gearing Ratio ---
            gr = self.galil_command("MG _GR", axis, expect_response=True)
            if gr is None or gr in ('?', '??', ''):
                gr = math.nan
            else:
                gr = float(gr)
            axis_data["gearing_ratio"] = gr

            data[axis] = axis_data

            # delay between axes querying
            time.sleep(0.2)

        return data

    def is_running(self, axis):
        """Checks if the axis is running"""
        cmd = 'MG _BG'
        resp = self.galil_command(cmd, axis)
        return resp

    def begin_motion(self, axis):
        """Begin motion for the specified axis using the BG command."""
        self.galil_command(command="BG", axis=axis)
        time.sleep(1)

        state = self.is_running(axis)
        if state == '1':
            print(f'Axis {axis} is in motion.')
        else:
            print(f'Axis {axis} did not move. Try again.')

    def set_relative_linearpos(self, axis, lindist, encodeunits=False):
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
            counts = round(lindist * countspermm, 3)
        except Exception as e:
            print(f'Exception occured: {e}')

        if encodeunits:
            counts = lindist
        resp = self.galil_command(command=f"PR{axis}={counts};")

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

    def set_motor_type(self, axis, motortype=1):
        """set the motor type for each axis. defaults to 1, the servo motor (3-phased brushless)"""
        resp = self.galil_command(command=f'MT{axis}={motortype};')
        return resp

    def set_off_on_error(self, axis, errtype):
        """Set the Off-On-Error (OE) function for the specified axis. 1 enables it, 0 disables it."""
        resp = self.galil_command(command=f'OE{axis}={errtype};')
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
        # Part of the homing process which requires jogging to the reverse limit switch and then defining the position of the axis at that limit as 0
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

    def enable_axis(self, axis):
        """Enable servo for an axis (e.g. A, B, C, D)."""
        cmd = f'SH{axis};'
        resp = self.galil_command(command=cmd)
        return resp

    def disable_axis(self, axis):
        """Motor off for an axis."""
        resp = self.galil_command(command=f"MO{axis}")
        return resp

    def check_axis_onoff(self, axis):
        """Motor off for an axis."""
        resp = self.galil_command(command=f"MG _MO{axis}")
        return resp
