import socket
import time
import base64
import numpy as np

class DLCSmart():
    def __init__(self, ip_addr, tcp_port=1998, upd_port=1999, buffer_size=1024, timeout=5):
        self.ip_addr = ip_addr
        self.tcp_port = tcp_port # TCP
        self.tcp_port = tcp_port # UDP
        self.buffer_size = buffer_size
        self.sock = None
        self.timeout = timeout
    
    # basic read and write functionality    
    def read_all(self, decode=True):
        """
        Handles decoding anything read out from the DLC Smart.
        """
        data = b""
        expect_prompt = False
        while True:
            try:
                chunk = self.sock.recv(1024)
            except self.sock.timeout:
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
        if not self.sock:
            raise ConnectionError("Not connected to device")
        self.sock.sendall((cmd + "\n").encode())
        time.sleep(0.01)
        if read_response:
            response = self.read_all(decode=decode)
            return response
        else:
            return True

    # connect and disconnect
    def connect(self):
        """
        Make the socket connection to the command port and read the
        welcome message.
        """
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.ip_addr, self.tcp_port))
        time.sleep(0.1)
        welcome_req = self.read_all()
        return True, welcome_req
    
    def close_connection(self):
        """
        Close the socket connection.
        """
        if self.sock:
            try:
                self.send_msg("(quit)", read_response=False)
            except Exception:
                pass
            self.sock.close()
            self.sock = None
   
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
            apply_dhcp = self.command("net-conf:apply")
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

    def set_scan_params(self, freq_min, freq_max, freq_step, direction):
        """
        Set all params to run a frequency sweep.
        """
        # set the scan to fast mode
        fast = self.param_set("frequency:scan-mode-fast", "#t")
        smin = self.param_set("frequency:frequency-min", freq_min)
        smax = self.param_set("frequency:frequency-max", freq_max)
        sstep = self.param_set("frequency:frequency-step", direction*freq_step)

    def check_scan_params(self):
        fast = self.param_ref("frequency:scan-mode-fast")
        smin = self.param_ref("frequency:frequency-min")
        smax = self.param_ref("frequency:frequency-max")
        sstep = self.param_ref("frequency:frequency-step")

        data = (fast, float(smin), float(smax), float(sstep))
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

    def clear_scan_data(self):
        """
        Clear the data from the most recent (prior or active) scan.
        """
        clear_data = self.command("frequency:fast-scan-clear-data")
        return clear_data

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
        Query the set frequency (GHz), actual frequency (GHz), and photocurrent (nA).
        For general monitoring purposes.
        """
        reset = self.command("lockin:lock-in-reset")
        time.sleep(0.3)
        photocurrent = self.param_ref("lockin:lock-in-value-nanoamp")
        if '#t' in photocurrent:
            photocurrent = photocurrent.strip('(').strip(' #t)')
        else:
            photocurrent = 'nan'
        set_frequency = self.param_ref("frequency:frequency-set")
        act_frequency = self.param_ref("frequency:frequency-act")
        value_dict = {'set_frequency': float(set_frequency),
                      'actual_frequency': float(act_frequency),
                      'photocurrent': float(photocurrent),
                      }
        return value_dict

    def get_scan_data(self):
        """
        Query the point number, set frequency (GHz), actual frequency (GHz), and
        photocurrent (nA) from a scan. For when you need to just get the data but
        weren't monitoring with timestamps.
        """
        scanning_query = self.param_ref("frequency:fast-scan-isscanning")
        if scanning_query == '#t':
            scanning = True
        elif scanning_query == '#f':
            scanning = False
        else:
            return scanning_query
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

