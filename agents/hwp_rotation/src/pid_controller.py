
########################################################################################################################
# Imports
########################################################################################################################

import subprocess
import os
import fcntl
import time
this_dir = os.path.dirname(__file__)

########################################################################################################################
# Primary Class
########################################################################################################################

class PID:
    # Information and variables used for PID connection
    def __init__(self, pid_ip, pid_port, verb = False):
        self.verb = verb
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.return_list = []
        self.PID_INFO = [pid_ip, pid_port]
        self.hex_freq = '00000'
        self.cur_freq = 0
        self.cur_direction = 0
        self.stop_params = [0.2, 0, 0]
        self.tune_params = [0.2, 63, 0]
        self.set_direction('0')

########################################################################################################################
# Subprocesses
########################################################################################################################

    # Converts the user input into a format the PID controller can read
    @staticmethod
    def convert_to_hex(value, decimal):
        temp_value = hex(int(10**decimal*float(value)))
        return ('0000' + str(temp_value)[2:].upper())[-4:]

    # Opens the connection with the PID controller and makes sure that nothing else is using the connection
    def open_line(self):
        while True:
            try:
                self.lock_file = open(os.path.join(this_dir, '.pid_port_busy'))
                fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(2)

    # Closes the connection with the PID controller
    def close_line(self):
        fcntl.flock(self.lock_file, fcntl.LOCK_UN)
        self.lock_file.close()

    # Gets the exponent in scientific notation
    @staticmethod
    def get_scale_hex(num, corr):
        expo = int(str(num*10**40 + 0.01).split('+')[1])-40
        digits = round(num*10**(-expo+4))

        expo_hex = str(hex(corr-expo))[2:]
        digits_hex = ('00000'+str(hex(digits))[2:])[-5:]

        return expo_hex + digits_hex

########################################################################################################################
# Main Processes
########################################################################################################################

    # Sets the direction if the CHWP; 0 for forward and 1 for backwards
    def set_direction(self, direction):
        self.open_line()   
        subprocess.call([os.path.join(self.script_dir, 'tune_direction'), self.PID_INFO[0], self.PID_INFO[1],
                         direction], stderr = subprocess.DEVNULL)
        if direction == '0':
            print('Forward')
            self.direction = 0
        elif direction == '1':
            print('Reverse')
            self.direction = 1

        self.return_messages()
        self.close_line()

    # Declare to memory what the CHWP frequency should be (does not actually change the frequency)
    def declare_freq(self, freq):
        if float(freq) <= 3.5:
            self.hex_freq = '0' + self.convert_to_hex(freq, 3)
            if self.verb:
                print('Frequency Setpoint = ' + str(freq) + ' Hz')
        else:
            if self.verb:
                print('Invalid Frequency')

    # Method which sets the setpoint to 0 Hz and stops the CHWP
    def tune_stop(self):
        self.open_line()
        if self.verb:
            print('Starting Stop')
        subprocess.call([os.path.join(self.script_dir, 'tune_stop'), self.PID_INFO[0], self.PID_INFO[1]], 
                         stderr = subprocess.DEVNULL)
        self.set_pid(self.stop_params)
        self.close_line()

    # Meathod which sets the setpoint to what is currently defined in memory
    def tune_freq(self):
        self.open_line()
        if self.verb:
            print('Staring Tune')
        subprocess.call([os.path.join(self.script_dir, 'tune_freq'), self.PID_INFO[0], self.PID_INFO[1],
                         self.hex_freq], stderr = subprocess.DEVNULL)
        self.set_pid(self.tune_params)
        self.close_line()

    # Returns the current frequency of the CHWP
    def get_freq(self):
        self.open_line()
        if self.verb:
            print('Finding CHWP Frequency')
        subprocess.call([os.path.join(self.script_dir, './get_freq'), self.PID_INFO[0], self.PID_INFO[1]],
                         stderr = subprocess.DEVNULL)
        self.return_messages()
        self.close_line()
        return self.cur_freq

    # Returns the current rotation direction
    def get_direction(self):
        self.open_line()
        if self.verb:
            print('Finding CHWP Direction')
        subprocess.call([os.path.join(self.script_dir, './get_direction'), self.PID_INFO[0], self.PID_INFO[1]],
                         stderr = subprocess.DEVNULL)
        self.return_messages()
        self.close_line()

    # Sets the PID parameters of the controller
    def set_pid(self, params):
        if self.verb:
            print('Setting PID Params')
        p_value = self.convert_to_hex(params[0], 3)
        i_value = self.convert_to_hex(params[1], 0)
        d_value = self.convert_to_hex(params[2], 1)
        subprocess.call([os.path.join(self.script_dir, './set_pid'), self.PID_INFO[0], self.PID_INFO[1], p_value,
                        i_value, d_value], stderr = subprocess.DEVNULL)
        self.return_messages()

    # Sets the conversion between feedback voltage and approximate frequency
    def set_scale(self, slope, offset):
        self.open_line()
        slope_hex = self.get_scale_hex(slope, 1)
        offset_hex = self.get_scale_hex(offset, 2)
        subprocess.call([os.path.join(self.script_dir, './set_scale'), self.PID_INFO[0], self.PID_INFO[1],
                         slope_hex, offset_hex], stderr = subprocess.DEVNULL)
        self.close_line()

########################################################################################################################
# Messaging
########################################################################################################################

    def return_messages(self):
        temp_return = self.read_log()
        self.return_list = self.decode_array(temp_return)
        self.remove_log()

    @staticmethod
    def read_log():
        with open('output.txt', 'rb') as log_file:
            return_string = log_file.read().split(b'\n')[-1]
            return return_string.decode('ascii').split('\r')[:-1]

    @staticmethod
    def remove_log():
        subprocess.call(['rm', 'output.txt'])

    def decode_array(self, input_array):
        output_array = list(input_array)
        
        for index, string in enumerate(list(input_array)):
            header = string[0]
            
            if header == 'R':
                output_array[index] = self.decode_read(string)
            elif header == 'W':
                output_array[index] = self.decode_write(string)
            elif header == 'E':
                output_array[index] = 'PID Enabled'
            elif header == 'D':
                output_array[index] = 'PID Disabled'
            elif header == 'P':
                pass
            elif header == 'G':
                pass
            elif header == 'X':
                output_array[index] = self.decode_measure(string)
            else:
                pass

        return output_array

    def decode_read(self, string):
        read_type = string[1:3]
        if read_type == '01':
            return 'Setpoint = ' + str(int(string[4:], 16)/1000.)
        elif read_type == '02':
            if int(string[4:], 16)/1000. > 2.5:
                print('Direction = Reverse')
                self.direction = 1
            else:
                print('Direction = Forward')
                self.direction = 0
        else:
            return 'Unrecognized Read'

    @staticmethod
    def decode_write(string):
        write_type = string[1:]
        if write_type == '01':
            return 'Changed Setpoint'
        elif write_type == '0C':
            return 'Changed Action Type'
        else:
            return 'Unrecognized Write'

    def decode_measure(self, string):
        measure_type = string[1:3]
        if measure_type == '01':
            self.cur_freq = float(string[3:])
            return float(string[3:])
        else:
            return 9.999

