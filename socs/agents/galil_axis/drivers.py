import math
import select
import time

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
        Check for and drain any remaining data from the TCP buffer.
        Return True or False depending on whether a ':' Galil prompt appears.

        """
        drained = b""

        # check if anything in buffer
        rlist, _, _ = select.select([self.comm], [], [], 0.2)
        if rlist:
            chunk = self.recv()
            if chunk:
                drained += chunk

                # --- if ':' in buffer, galil is ready to receive command, return True ---
                if drained.endswith(b"\r:") or b":" in drained:
                    return True
                else:
                    # means more drainage necessary
                    print(f"Drained {len(drained)} bytes, but no ':' prompt seen.")
                    return False
        else:
            # no data pending in buffer -- ready to send new command!
            return True

    def _is_ready(self, max_attempts=3, delay=0.05):
        """Try up to max_attempts to drain prompt until controller is ready."""
        for attempt in range(max_attempts):
            if self._drain_prompt():
                return True
            time.sleep(delay)

        raise Exception(
            "':' not seen to indicate Galil ready to receive command. "
            "Flushed out buffer 3 times — likely needs to be flushed more."
        )

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

        # check if Galil is ready to receive commands
        self._is_ready()

        self.send(msg)

        if not expect_response:
            resp = ''
            return resp
        else:
            for attempt in range(retries):
                resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n")

                if resp in ("?", "??", ""):
                    self._drain_prompt()
                    self.send(b"TC1\r")  # ask galil why '?'
                    tc_resp = self.recv().decode("ascii", errors="ignore").strip(":\r\n ")

                    if tc_resp.startswith("5"):
                        print("TC1=5 (Input buffer full) — clearing input buffer")
                        self.send(b"CI -1;\r")
                    else:
                        print(f"TC error response: {tc_resp}")

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

        state = self.is_running(axis)
        state = str(int(float(state)))
        if state == '1':
            msg = f'Axis {axis} is in motion.'
            return True, msg
        elif state == '0':
            msg = f'Axis {axis} is not moving. Retry command if needed.'
            return False, msg

    def set_relative_position(self, axis, distance, counts_per_unit=None):
        """
        Move axis by a relative distance (in calibration units such as
        mm or deg or raw encoder counts). If `counts_per_unit` is None,
        assume raw counts.

        """
        counts = distance if counts_per_unit is None else round(distance * counts_per_unit, 3)
        return self.galil_command("PR", axis=axis, value=counts)

    def set_absolute_position(self, axis, position, counts_per_unit=None):
        """
        Set absolute position for an axis in units or encoder counts.

        """
        counts = position if counts_per_unit is None else round(position * counts_per_unit, 3)
        return self.galil_command("PA", axis=axis, value=counts)

    def release_brake(self, output_num):
        """
        Release brake to axis by using the GalilDMC SB command which sets the digital
        output to 1.

        """
        resp = self.galil_command(command=f"SB {output_num}")
        return resp

    def engage_brake(self, output_num):
        """
        Engage the brake for the specified axis using the Galil CB command.

        """
        resp = self.galil_command(command=f"CB {output_num}")
        return resp

    def get_brake_status(self, axis, output_num):
        """
        Return brake status for axis via @OUT[n].

        """
        val = self.galil_command(command=f"MG @OUT[{output_num}]",
                                 expect_response=True)

        state = int(round(float(val)))

        if state == 1:
            status = "Brake Released"
        if state == 0:
            status = "Brake Engaged"

        return state, status

    def get_thermistor_voltage(self, axis, output_num):
        """
        Return thermistor voltage value for an axis via @AN[n]
        """
        val = self.galil_command(command=f"MG @AN[{output_num}]", expect_response=True)

        temp_voltage = float(val)

        return temp_voltage

    def get_motor_type(self, axis):
        """
        Return motor type for given axis via MG _MT{axis}.

        """
        resp = self.galil_command("MG _MT", axis=axis, expect_response=True)
        return resp

    def get_gearing_ratio(self, axis):
        """
        Return gearing ratio for given axis.

        """
        resp = float(self.galil_command(command=f'MG _GR{axis}', expect_response=True))
        return resp

    def get_gearing_lead(self, axis):
        """
        Return gearing lead for a given follower axis. A response of "0" means the axis is a leader.
        """
        resp = self.galil_command(command=f'GA{axis}=?', expect_response=True)

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

    # initialization required if galil motor has sinusoidal amplifiers
    def enable_sin_commutation(self, axis):
        """
        For axes with a sinusoidal amplifier, the BA command is necessary to configure
        each axis for sinusoidal commutation

        """
        resp = self.galil_command(command=f'BA{axis};')
        return resp

    # initialization required if galil motor has sinusoidal amplifiers
    def set_magnetic_cycle(self, axis, val='3276.8'):
        """
        Defines the length of the motors magnetic cycle in encoder counts,
        required for correctly configuring sinusoidal commutation. Default is 3276.8

        """
        resp = self.galil_command(command=f'BM{axis}={val};')
        return resp

    # initialization required if galil motor has sinusoidal amplifiers
    def set_dwell_times(self, t_first, t_second):
        """
        Define the dwell times used for sinusoidal commutation initialization.

        This command sets the timing parameters for the Galil BZ command,
        specifying how long the motor will hold at the first and second
        magnetic positions during commutation (in milliseconds). These
        parameters must be defined before executing the BZ command.

        """
        cmd = f'BZ <{t_first}>{t_second}'
        resp = self.galil_command(command=cmd)
        return resp

    def initialize_axis(self, axis, val):
        """
        Initializes axes configured for sinusoidal commutation. BZ command
        will drive the motor to 2 different magnetic positions and then set
        the appropriate commutation angle. Cannot command with BZ unless BA
        and BM commands are sent first.

        """
        resp = self.galil_command(command=f'BZ{axis}={val};')
        return resp

    def define_position(self, axis, val=0):
        """
        Redefines current axis position to user specified value.
        Useful for homing procedure. Default is 0.

        """
        resp = self.galil_command(command=f'DP{axis}={val};')
        return resp

    def set_limit_switch(self, axis, val=3):
        """
        Enable/disable limit switch detection on a given axis (LDx=val).

        val 0 = Disable no limit switches (all enabled)
        val 1 = Disable forward limit switch
        val 2 = Disable reverse limit switch
        val 3 = Disable both forward and reverse limit switches

        """
        resp = self.galil_command(command=f'LD{axis}={val};')
        return resp

    def get_limit_switch_setting(self, axis):
        """
        Return disable limit switch setting where 0 = Both limits enabled, 1 = Forward disabled, 2 = Reverse disabled, 3 = Both forward and reverse disabled

        """
        resp = self.galil_command(command="MG _LD", axis=axis, expect_response=True)

        resp = int(round(float(resp)))

        return resp

    def set_limitswitch_polarity(self, pol=1):
        """
        CN -1 means active low, CN +1 is active high. Default is  1
        (active high).

        """
        resp = self.galil_command(command=f'CN {pol};')
        return resp

    def get_limitswitch_polarity(self):
        """
        CN -1 means active low, CN +1 is active high. Our system is 1 (active high).

        """
        val = self.galil_command(command="MG _CN", expect_response=True)

        state = int(round(float(val)))

        if state == 1:
            status = "+1; active high"
        if state == -1:
            status = "-1, active low"

        return state, status

    def stop_motion(self, axis):
        """
        Stop motion.

        """
        cmd = f"ST {axis};"
        resp = self.galil_command(command=cmd)
        return resp

    def set_gearing(self, order):
        """
        Set gearing for defining follower and leader axes.
        The `order` string defines the sequence of operations.
        For example: `order = ',A,C'` means axis **B** follows
        **A**, and axis **D** follows **C** —the commas correspond
        to axes A, B, C, D in order.

        """
        resp = self.galil_command(command=f"GA {order};")
        return resp

    def set_gearing_ratio(self, order):
        """
        Set the gearing ratio for follower axes relative to their leader axes.
        A ratio of 1 means the follower moves at the same speed as its leader.
        For example, `GR 1,1` sets the gearing ratios for axes B and D

        """
        resp = self.galil_command(command=f"GR {order};")
        return resp

    def set_jog_speed(self, axis, speed):
        """
        Set jog speed for axis. Does not begin motion, just sets up speed
        for when ready to begin motion.

        """
        cmd = f"JG{axis}={speed};"
        resp = self.galil_command(command=cmd)
        return resp

    def set_speed(self, axis, speed):
        """
        Set speed for axis for use in commands like PR/PA (relative and absolute
        position). Does not begin motion, just defines speed for when
        ready to begin motion. Units of speed is in raw encoder units (counts/s).

        """
        cmd = f"SP{axis}={speed};"
        resp = self.galil_command(command=cmd)
        return resp

    def get_speed(self, axis):
        """
        Return speed for axis via MG _SP{axis}. Units of speed is in raw encoder units (counts/s).
        """
        resp = self.galil_command("MG _SP", axis=axis, expect_response=True)
        return resp

    def set_acceleration(self, axis, acc):
        """
        Set acceleration for axis. (encoder counts/sec^2) Value should be a power of 2. (e.g. 4096, 8192)
        """
        cmd = f"AC{axis}={acc};"
        resp = self.galil_command(command=cmd)
        return resp

    def get_acceleration(self, axis):
        """
        Return acceleration for given axis via "MG _AC{axis}". Units of acceleration are in raw encoder units (counts/s^2).
        """
        resp = self.galil_command("MG _AC", axis=axis, expect_response=True)
        return resp

    def set_deceleration(self, axis, decel):
        """
        Set deceleration for axis. Units are encoder counts/s^2
        """
        cmd = f"DC{axis}={decel};"
        resp = self.galil_command(command=cmd)
        return resp

    def get_deceleration(self, axis):
        """
        Return deceleration for given axis via "MG _DC{axis}". Units are in raw encoder units (counts/s^2).
        """
        resp = self.galil_command("MG _DC", axis=axis, expect_response=True)
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
            resp = self.galil_command("SH", axis=axis)
        elif state == 'disable':
            resp = self.galil_command("MO", axis=axis)
        return resp

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
