import serial
import time
import toml
#import socket

from socs.tcp import TCPInterface

class GalilStage():
    def __init__(self, ip, configfile, port=23, timeout=10): #  port='/dev/ttyUSB0',
        """Interface class for connecting to GalilStageController for SO SAT Coupling Optics."""
        self.ip = ip
        self.configfile = configfile
        self.port = port
        self.timeout = timeout

        super().__init__(ip, port, timeout)

    def get_data(self):
        """
        Gets the position, velocity, and torque data from the galil stage motor and returns in a usable format.
        """
        axes = ['A', 'B', 'C', 'D']
        data = {}

        for axis in axes:
            data[axis] = {
                'position': float(self.query_status(f"_TP{axis}").strip(': \r\n')),
                'velocity': float(self.query_status(f"_TV{axis}").strip(': \r\n')),
                'torque': float(self.query_status(f"_TT{axis}").strip(': \r\n')),
               # 'gearing_ratio': float(self.query_status(f"_GA{axis}").strip(': \r\n')),
            }

        return data
    

    def connect(self):
        """Open a TCP socket connection to the Galil controller."""
        try:
            self.sock = socket.create_connection((self.ip, self.port), timeout=self.timeout)
            print(f"Connected to Galil at {self.ip}:{self.port}")
            return True
        except Exception as e:
            print(f"Failed to connect to Galil: {e}")
            self.sock = None
            return False


    def disconnect(self):
        """Close the TCP socket connection."""
        if self.sock:
            self.sock.close()
            self.sock = None
            print("Disconnected from Galil.")


    def query_status(self, code):
        """Send MG query, e.g. query_status('_MOA')."""
        return self.send_command(f"MG {code}")
   
    def send_command(self, cmd):
        """Send a command to the Galil controller and return the response."""
        if not self.sock:
            raise RuntimeError("Not connected to Galil.")
        try:
            # Send ASCII command terminated with carriage return
            self.sock.sendall((cmd + '\r').encode('ascii'))
            # Receive ASCII response
            resp = self.sock.recv(4096).decode('ascii', errors='ignore')
            return resp
        except Exception as e:
            print(f"Socket error during send_command: {e}")
            self.disconnect()
            raise
    
    #def send_command(self, cmd):
    #    if not self.sock:
    #        raise RuntimeError("Not connected to Galil.")
    #    self.sock.sendall((cmd + "\r").encode("ascii"))
    #    return self.sock.recv(1024).decode("ascii", errors="ignore")
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
