import math
import os
import select
import time

import serial
import yaml

from socs.tcp import TCPInterface


class GalilAxis(TCPInterface):
    def __init__(self, ip, port=23, timeout=10):
        """Interface class for connecting to GalilStageController for SO SAT Coupling Optics."""
        self.ip = ip
        self.port = port
        self.timeout = timeout

        super().__init__(self.ip, self.port, self.timeout)

    def _drain_prompt(self):
        """
        Drain the TCP buffer until a Galil ':' prompt is seen or timeout occurs.
        If a '?' is detected, query TC1 for an error code.
        Handles 'Input buffer full' (TC1=5) by pausing and waiting for the controller
        to clear before allowing new commands.
        """
        if os.environ.get("GALIL_TEST_MODE"):
            return b":"

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
                      expect_response=False, retries=3):
        """
        Send a command to the Galil controller and optionally return its response.

        """

        # --- Build command string ---
        if axis is not None and value is not None:
            cmd = f"{command}{axis}={value}"
        elif axis is not None:
            cmd = f"{command}{axis}"
        elif value is not None:
            cmd = f"{command}={value}"
        else:
            cmd = f"{command}"

        msg = f"{cmd}\r".encode("ascii")

        # ---drain the prompt ---
        self._drain_prompt()
        time.sleep(0.100)
        self.send(msg)

        if not expect_response:
            resp = ''
            return resp

        # --- receive and retry on '?' ---
        for attempt in range(retries):
            resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n")

            if resp in ("?", "??", ""):
                self._drain_prompt()
                time.sleep(0.1)
                self.send(msg)
                continue
            else:
                break

        return resp

    def get_relative_position(self, axis, movetype=None, counts_per_mm=None, counts_per_deg=None):
        """
        Query the relative position set for a specified axis. Converts counts to physical units if
        movetype is 'linear' or 'angular'.

        """
        units_map = {'linear': 'mm', 'angular': 'deg'}
        units = units_map.get(movetype, '')

        # --- Query the controller using robust galil_command() ---
        value = self.galil_command("MG _PR", axis, expect_response=True)
        try:
            value = float(value)
        except Exception as e:
            print(f'Exception occurred, returning nan: {e}')
            return math.nan, units

        # If no movetype, just return raw counts
        if movetype is None:
            return value

        # Optional conversion if provided
        if movetype == 'linear' and counts_per_mm:
            value /= counts_per_mm
            return value, 'mm'
        elif movetype == 'angular' and counts_per_deg:
            value /= counts_per_deg
            return value, 'deg'

    def get_data(self, axes=None):
        """
        Query position (TP), velocity (TV), torque (TT), and position error (TE)
        for all axes in one batch, then subset results for the requested axes.

        """

        data = {}

        # Order of axes is always A–H on Galil (up to 8 possible)
        all_axes = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']

        tp = [float(x) for x in self.galil_command('TP', expect_response=True).split(',')]
        tv = [float(x) for x in self.galil_command('TV', expect_response=True).split(',')]
        tt = [float(x) for x in self.galil_command('TT', expect_response=True).split(',')]
        te = [float(x) for x in self.galil_command('TE', expect_response=True).split(',')]

        # Determine how many valid axes are reported (Galil reports starting from A)
        n_axes = max(len(tp), len(tv), len(tt), len(te))
        active_axes = all_axes[:n_axes]

        if axes is None:
            axes = active_axes

        # --- Build dict per axis ---
        for i, axis in enumerate(active_axes):
            if axis not in axes:
                continue  # skip axes user doesn't care about

            data[axis] = {
                'position': tp[i],
                'velocity': tv[i],
                'torque': tt[i],
                'position_error': te[i]
            }

        if axes:
            for axis in axes:
                gr = float(self.galil_command(command=f'MG _GR{axis}', expect_response=True))
                data[axis]["gearing_ratio"] = gr

        return data

    def is_running(self, axis):
        """
        Checks if the axis is moving.

        """
        cmd = f'MG _BG{axis}'
        resp = self.galil_command(cmd, expect_response=True)
        return resp

    def begin_motion(self, axis):
        """
        Begin motion for the specified axis using the BG command.

        """
        self.galil_command(command="BG", axis=axis)
        time.sleep(1)

        state = self.is_running(axis)
        if state == '1':
            print(f'Axis {axis} is in motion.')
        else:
            print(f'Axis {axis} did not move. Try again.')

    def set_relative_position(self, axis, distance, counts_per_unit=None, encodeunits=False):
        """
        Move axis by a relative distance (in units or encoder counts.

        """
        if not encodeunits and counts_per_unit is None:
            raise ValueError("counts_per_unit required when encodeunits=False")

        counts = distance if encodeunits else round(distance * counts_per_unit, 3)
        return self.galil_command("PR", axis=axis, value=counts)

    def set_absolute_position(self, axis, position, counts_per_unit=None, encodeunits=False):
        """
        Set absolute position for an axis in units or encoder counts.

        """
        if not encodeunits and counts_per_unit is None:
            raise ValueError("counts_per_unit required when encodeunits=False")

        counts = position if encodeunits else round(position * counts_per_unit, 3)
        return self.galil_command("PA", axis=axis, value=counts)

    def release_brake(self, output_num):
        """
        Release brake to axis by using the GalilDMC SB command which sets the digital
        output to 1.

        """
        resp = self.galil_command(command="SB", value=output_num)
        return resp

    def engage_brake(self, output_num):
        """
        Engage the brake for the specified axis using the Galil CB command.

        """
        resp = self.galil_command(command="CB", value=output_num)
        return resp

    def get_brake_status(self, axis, output_map):
        """
        Return brake status for axis via @OUT[n].

        """
        output_num = output_map[axis]
        query_str = f"@OUT[{output_num}]"
        val = self.galil_command(command="MG", value=query_str)

        try:
            state = int(round(float(val)))
        except (TypeError, ValueError):
            print(f"Could not parse brake value '{val}' for axis {axis}.")
            return {axis: {"state": None, "status": "Unknown"}}

        if state == 1:
            status = "Brake Released"
        if state == 0:
            status = "Brake Engaged"

        return {axis: {"state": state, "status": status}}

    def get_motor_type(self, axis):
        """
        Return motor type for given axis via MG _MT{axis}.

        """
        resp = self.galil_command(f"MG _MT", axis=axis, expect_response=True)
        return resp

    def get_gearing_ratio(self, axis):
        """
        Return gearing ratio for given axis.

        """
        resp = float(self.galil_command(command=f'MG _GR{axis}', expect_response=True))
        return resp

    def set_motor_type(self, axis, motortype):
        """
        Set the motor type for each axis. The setting is typically 1, the servo motor (3-phased brushless)

        """
        resp = self.galil_command(command=f'MT{axis}={motortype};')
        return resp

    def get_off_on_error(self, axis):
        """
        Query the Off-On-Error (OE) state for an axis and return raw + human-readable.

        """
        resp = self.galil_command("MG _OE", axis=axis, expect_response=True)
        try:
            val = int(float(resp))
        except Exception:
            print(f"Unexpected response from MG _OE{axis}: {resp}")
            return None, "unknown"

        human_state = "enabled" if val == 1 else "disabled" if val == 0 else f"unknown ({val})"
        return val, human_state

    def set_off_on_error(self, axis, errtype):
        """
        Set the Off-On-Error (OE) function for the specified axis.

        """
        resp = self.galil_command(command=f'OE{axis}={errtype};')
        return resp

    def get_amp_gain(self, axis):
        """
        Query the amplifier gain (AG) value for an axis.

        """
        return self.galil_command("MG _AG", axis=axis, expect_response=True)

    def set_amp_gain(self, axis, val):
        """
        Set amplifier current/voltage gain for internal amplifier per axis.

        """
        resp = self.galil_command(command=f'AG{axis}={val};')
        return resp

    def get_torque_limit(self, axis):
        """
        Query the motor torque limit (TL) value for an axis.
        """
        return self.galil_command("MG _TL", axis=axis, expect_response=True)

    def set_torque_limit(self, axis, val):
        """
        Set motor torque limit per axis.

        """
        resp = self.galil_command(command=f'TL{axis}={val};')
        return resp

    def get_amp_currentloop_gain(self, axis):
        """
        Query the amplifier current loop gain (AU) value for an axis.

        """
        return self.galil_command("MG _AU", axis=axis, expect_response=True)

    def set_amp_currentloop_gain(self, axis, val):
        """
        Set amplifier current loop gain per axis.

        """
        resp = self.galil_command(command=f'AU{axis}={val};')
        return resp

    # init
    def enable_sin_commutation(self, axis):
        """
        For axes with a sinusoidal amplifier, the BA command is necessary to configure
        each axis for sinusoidal commutation

        """
        resp = self.galil_command(command=f'BA{axis};')
        return resp

    # init
    def set_magnetic_cycle(self, axis, val='3276.8'):
        """
        Defines the length of the motors magnetic cycle in encoder counts,
        required for correctly configuring sinusoidal commutation. Default is 3276.8

        """
        resp = self.galil_command(command=f'BM{axis}={val};')
        return resp

    # init
    def initialize_axis(self, axis, val):
        """
        Initializes axes configured for sinusoidal commutation. BZ command
        will drive the motor to 2 different magnetic positions and then set
        the appropriate commutation angle. Cannot command with BZ unless BA
        and BM commands are sent first.

        """
        resp = self.galil_command(command=f'BZ{axis}={val};')
        return resp

    # home
    def define_position(self, axes, val=0):
        """
        Redefines current axis position to user specified value.
        Useful for homing procedure.

        """
        resp = self.galil_command(command=f'DP{axis}={val};')
        return resp

    def disable_limit_switch(self, axis):
        """
        Disable limit switch detection on a given axis (LDx=3).

        """
        resp = self.galil_command(command=f'LD{axis}=3;', expect_response=True)
        return resp

    def set_limitswitch_polarity(self, pol=1):
        """
        CN -1 means active low, CN +1 is active high. And we want active high.

        """
        resp = self.galil_command(command=f'CN {pol};')
        return resp

    def stop_motion(self, axis):
        """
        Stop motion.

        """
        cmd = f"ST {axis};"
        resp = self.galil_command(command=cmd)
        return resp

    def set_gearing(self, order):
        """
        Set gearing: order is order of opertions in string: ',A,,C'.

        """
        resp = self.galil_command(command=f"GA {order};")
        return resp

    def set_gearing_ratio(self, order):
        """
        Set gearing ratios, e.g. GR -1,1 for axes B and D.

        """
        resp = self.galil_command(command=f"GR {order};")
        return resp

    def jog_axis(self, axis, speed):
        """
        Set jog speed for axis. Does not begin motion, just sets up speed
        for when ready to begin motion.

        """
        cmd = f"JG{axis}={speed};"
        resp = self.galil_command(command=cmd)
        return resp

    def set_motor_state(self, axis, state):
        """
        Enable or disable a motor, then verify its state (0='on', 1='off').

        """
        state = state.lower().strip()
        if state not in ('enable', 'disable'):
            raise ValueError("state must be 'enable' or 'disable'.")

        # --- Execute command ---
        if state == 'enable':
            self.galil_command("SH", axis=axis)
        elif state == 'disable':
            self.galil_command("MO", axis=axis)

        # --- Allow controller to settle ---
        time.sleep(1.0)

        # --- Query new state ---
        status, human_state = self.get_motor_state(axis=axis)

        return status, human_state

    def get_motor_state(self, axis):
        """
        Query and interpret whether a motor is ON or OFF for a given axis.

        """
        resp = self.galil_command(command=f"MG _MO{axis}", expect_response=True)
        try:
            state = int(float(resp))
        except Exception:
            print(f"Unexpected response from MG _MO{axis}: {resp}")
            return None, "unknown"

        # --- Interpret the raw output ---
        human_state = "off" if state == 1 else "on" if state == 0 else f"unknown ({state})"
        return state, human_state
