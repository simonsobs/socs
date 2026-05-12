import base64
import select
import time

import numpy as np

from socs.tcp import TCPInterface


class DLCSmart(TCPInterface):
    def __init__(self, ip_addr, port=1998, timeout=5):
        super().__init__(ip_addr, port, timeout)

    def drain_buffer(self, decode=True):
        drained = b""
        rlist, _, _ = select.select([self.comm], [], [], 0.2)
        if rlist:
            chunk = self.recv()
            if chunk:
                drained += chunk
                if drained.endswith(b"\n> ") or drained.endswith(b"> "):
                    return True
                else:
                    print("not fully drained")
                    return False
        else:
            return True

    def _is_ready(self, max_attempts=3, delay=0.05):
        for attempt in range(max_attempts):
            if self.drain_buffer():
                return True
            time.sleep(delay)

    # basic read and write functionality

    def read_all(self, decode=True):
        """
        Handles decoding anything read out from the DLC Smart.
        """
        data = b""
        expect_prompt = False
        while True:
            try:
                chunk = self.recv(1024)
            except self.timeout:
                break
            data += chunk
            if expect_prompt and data.endswith(b">"):
                break
            if not expect_prompt and b"\n" in chunk:
                break
        if decode:
            return data.decode('ascii', errors='ignore').replace('\r', '').strip('\n> ')
        else:
            return data

    def send_msg(self, cmd, read_response=True, decode=True):
        """
        Encode the message, send to the DLC Smart, and read
        back the response.
        """
        self._is_ready()
        self.send((cmd + "\n").encode())
        time.sleep(0.01)
        if read_response:
            response = self.read_all(decode=decode)
            return response
        else:
            return True

    # formatting for requests, param setting, and commands

    def param_ref(self, param, printout=False):
        """
        Request a parameter from the DLC Smart and read in the
        response.

        Input
        -----
        param (str): Name of the parameter from the Command Reference

        Return
        ------
        resp: The response from the DLC Smart
        """
        msg = f"(param-ref '{param})"
        resp = self.send_msg(msg)
        if printout:
            print(f"{param}: ", resp)
        return resp

    def param_set(self, param, val):
        """
        Set a parameter and read in the response from the DLC Smart.

        Input
        -----
        param (str): Name of the parameter from the Command Reference
        val (list): List of values for the parameter

        Return
        ------
        resp: The response from the DLC Smart
        """
        msg = f"(param-set! '{param} {val})"
        resp = self.send_msg(msg)
        return resp

    def command(self, param, decode=False, vals=[]):
        """
        Execute a command to the DLC Smart.

        Input
        -----
        param (str): Name of the parameter from the Command Reference
        vals (list, optional): List of values for the parameter. Some commands
                               do not require values.

        Return
        ------
        resp: The response from the DLC Smart
        """
        msg = f"(exec '{param}"
        if len(vals):
            for val in vals:
                msg += " " + str(val)
        msg += ")"
        resp = self.send_msg(msg, decode=decode)
        return resp

    # network operations and checks

    def get_ip(self):
        resp = self.param_ref("net-conf:ip-addr")
        self.ip_address = resp
        return resp

    def set_dhcp(self, apply=False):
        resp = self.command("net-conf:set-dhcp")
        if apply:
            self.command("net-conf:apply")
            return
        return resp

    def get_system_label(self):
        """
        Request the system label (str). Use to check that you are actually
        talking to the DLC Smart.
        """
        resp = self.param_ref("general:system-label")
        return resp

    # laser emission
    def check_laser_emission(self):
        """
        Request the status of laser emission (bool).
        """
        resp = self.param_ref("laser-operation:emission-global-enable")
        return resp

    def laser_emission_on(self):
        """
        Set the laser emission for both lasers to on (True).
        """
        resp = self.param_set("laser-operation:emission-global-enable", "#t")
        return resp

    def laser_emission_off(self):
        """
        Set the laser emission for both lasers to off (False).
        """
        resp = self.param_set("laser-operation:emission-global-enable", "#f")
        return resp

    # voltage bias
    def check_bias(self, printall=False):
        """
        Request the bias amplitude and offset (ints or floats).
        """
        amp = self.param_ref("lockin:mod-out-amplitude")
        offset = self.param_ref("lockin:mod-out-offset")
        if printall:
            print(f"Tx Bias Amplitude: {amp} V")
            print(f"Tx Bias Offset: {offset} V")
        return float(amp), float(offset)

    def set_bias_to_zero(self):
        """
        Set the bias amplitude and bias offset to zero.
        """
        resp = self.command("lockin:mod-out-set-to-zero")
        return resp

    def set_bias_to_default(self):
        """
        Set the bias amplitude and bias offset to the default values.
        """
        resp = self.command("lockin:mod-out-set-to-default")
        return resp

    # frequency and scan functions
    def set_frequency(self, frequency):
        """
        Set the frequency of the system.

        Input
        -----
        frequency (float): The frequency to set the system to, in GHz
        """
        resp = self.param_set("frequency:frequency-set", frequency)
        return resp

    def clear_scan_data(self):
        """
        Clear any cached scan data from the DLC Smart.
        """
        resp = self.command("frequency:fast-scan-clear-data")
        return resp

    def set_scan_params(self, freq_min, freq_max, freq_step, direction, int_time):
        """
        Set all params to run a frequency sweep.
        """
        # set the scan to fast mode
        self.param_set("frequency:scan-mode-fast", "#t")
        self.param_set("frequency:frequency-min", freq_min)
        self.param_set("frequency:frequency-max", freq_max)
        self.param_set("frequency:frequency-step", direction * freq_step)
        self.param_set("lockin:integration-time", int_time)

    def check_scan_params(self):
        fast = self.param_ref("frequency:scan-mode-fast")
        smin = self.param_ref("frequency:frequency-min")
        smax = self.param_ref("frequency:frequency-max")
        sstep = self.param_ref("frequency:frequency-step")
        sint = self.param_ref("lockin:integration-time")

        data = (fast, float(smin), float(smax), float(sstep), float(sint))
        return data

    def stop_scan(self):
        """
        Stops a scan.
        """
        resp = self.command("frequency:fast-scan-stop")
        return resp

    def start_scan(self):
        """
        Starts a scan.
        """
        resp = self.command("frequency:fast-scan-start")
        return resp

    # queries and basic commands
    def get_actual_frequency(self):
        """
        Query the actual frequency (GHz). Use to quickly check when
        setting a new frequency.
        """
        act_frequency = self.param_ref("frequency:frequency-act")
        return float(act_frequency)

    def sampling(self):
        """
        Query the following values:
          - Set frequency (GHz)
          - Actual frequency (GHz)
          - Photocurrent (nA)
          - Bias voltage (V)
          - Bias offset (V)
          - Laser emission on (boolean)
          - Scan mode ('fast' or 'precise')
          - Scan minimum frequency (GHz)
          - Scan maximum frequency (GHz)
          - Scan step size (GHz)
          - Scan direction (1 for increasing frequency, -1 for decreasing frequency)
          - Scan integration time (ms)
        For general monitoring purposes.
        """
        self.command("lockin:lock-in-reset")
        time.sleep(0.3)

        # Photocurrent
        photocurrent = self.param_ref("lockin:lock-in-value-nanoamp")
        if '#t' in photocurrent:
            photocurrent = photocurrent.strip('(').strip(' #t)')
        else:
            photocurrent = 'nan'

        # Set and actual frequency
        set_frequency = self.param_ref("frequency:frequency-set")
        act_frequency = self.param_ref("frequency:frequency-act")

        # Bias voltage and offset
        bias = self.check_bias()

        # Laser emission
        laser_status = self.check_laser_emission()
        if "#t" in laser_status:
            lasers_on = True
        elif "#f" in laser_status:
            lasers_on = False

        # Scan parameters
        scan_params = self.check_scan_params()
        if "#t" in scan_params[0]:
            scan_mode = 'fast'
        elif "#f" in scan_params[0]:
            scan_mode = 'precise'

        value_dict = {'set_frequency': float(set_frequency),
                      'actual_frequency': float(act_frequency),
                      'photocurrent': float(photocurrent),
                      'bias_voltage': float(bias[0]),
                      'bias_offset': float(bias[1]),
                      'lasers_on': lasers_on,
                      'scan_mode': scan_mode,
                      'scan_min_frequency': float(scan_params[1]),
                      'scan_max_frequency': float(scan_params[2]),
                      'scan_step': abs(scan_params[3]),
                      'scan_direction': int(np.sign(scan_params[3])),
                      'integration_time': float(scan_params[4]),
                      }
        return value_dict

    def get_scan_data(self):
        """
        Query the point number, set frequency (GHz), actual frequency (GHz), and
        photocurrent (nA) from a scan. For when you need to just get the data but
        weren't monitoring with timestamps.

        Note: This function exists in the driver for non-OCS usage. It is not intended
              for OCS/SOCS workflows.
        """
        start_ix = 0
        data = {'scan_point_number': [],
                'scan_set_frequency': [],
                'scan_actual_frequency': [],
                'scan_photocurrent': []}
        get_point_num = self.command("frequency:fast-scan-get-data", decode=False, vals=[0, start_ix, 1024])
        pointnum_raw = base64.b64decode(get_point_num)
        pointnum_readable = np.frombuffer(pointnum_raw, dtype=np.float64)

        while len(get_point_num):
            get_set_freq = self.command("frequency:fast-scan-get-data", decode=False, vals=[1, start_ix, 1024])
            fset_raw = base64.b64decode(get_set_freq)
            fset_readable = np.frombuffer(fset_raw, dtype=np.float64)

            get_act_freq = self.command("frequency:fast-scan-get-data", decode=False, vals=[6, start_ix, 1024])
            fact_raw = base64.b64decode(get_act_freq)
            fact_readable = np.frombuffer(fact_raw, dtype=np.float64)

            get_photocurrent = self.command("frequency:fast-scan-get-data", decode=False, vals=[2, start_ix, 1024])
            pcur_raw = base64.b64decode(get_photocurrent)
            pcur_readable = np.frombuffer(pcur_raw, dtype=np.float64)

            for i in range(len(pointnum_readable)):
                data['scan_point_number'].append(pointnum_readable[i])
                data['scan_set_frequency'].append(fset_readable[i])
                data['scan_actual_frequency'].append(fact_readable[i])
                data['scan_photocurrent'].append(pcur_readable[i])

            start_ix += 1024
            get_point_num = self.command("frequency:fast-scan-get-data", decode=False, vals=[0, start_ix, 1024])
            pointnum_raw = base64.b64decode(get_point_num)
            pointnum_readable = np.frombuffer(pointnum_raw, dtype=np.float64)

        return data
