# For a deeper understanding of the pid command message syntax refer to: https://assets.omega.com/manuals/M3397.pdf
import socket
import time
from dataclasses import dataclass, field
from typing import Optional, Union


def retry_multiple_times(loops=3):
    def dec_wrapper(func):
        def inner(*args, **kwargs):
            for i in range(loops):
                try:
                    return func(*args, **kwargs)
                except BaseException:
                    time.sleep(0.2)
            print(f'Could not complete {func.__name__} after {loops} attempt(s)')
            return DecodedResponse(msg_type='error', msg='Read Error')
        return inner
    return dec_wrapper


@dataclass
class DecodedResponse:
    msg_type: str
    msg: str
    measure: Optional[Union[int, float]] = field(default=None)


class PID:
    """Class to communicate with the Omega CNi16D54-EIT PID controller.

    Args:
        ip (str): IP address for the controller.
        port (int): Port number for the socket connection.
        verb (bool): Verbose output setting. Defaults to False.

    Attributes:
        verb (bool): Verbose output setting.
        hex_freq (str): Currently declared rotation frequency in hexadecimal.
        conn (socket.socket): Socket object with open connection to the PID
            controller.

    """

    def __init__(self, ip, port, verb=False):
        self.verb = verb
        self.ip = ip
        self.port = port
        self.hex_freq = '00000'
        self.conn = self._establish_connection(self.ip, int(self.port))

    @staticmethod
    def _establish_connection(ip, port, timeout=2):
        """Connect to PID controller.

        Args:
            ip (str): IP address for controller.
            port (int): Port number for socket connection.
            timeout (float): Time in seconds to wait for comms until timeout
                occurs.

        Returns:
            socket.socket: Socket object with open connection to the PID
                controller.

        """
        conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        conn.settimeout(timeout)
        # unit tests might fail on first connection attempt
        attempts = 3
        for attempt in range(attempts):
            try:
                conn.connect((ip, port))
                break
            except (ConnectionRefusedError, OSError):
                print(f"Failed to connect to device at {ip}:{port}")
        else:
            raise RuntimeError('Could not connect to PID controller')
        return conn

    @staticmethod
    def _convert_to_hex(value, decimal):
        """Converts the user input into a format the PID controller can
        read.

        Args:
            value (float): value to be converted
            decimal (int): number of decimal places needed by the PID
                           controller. Depends on what the converted
                           value is needed for (e.g. the setpoint values
                           need take the form X.XXX so decimal=3)

        Returns:
            str: encoded hex string

        Examples:
            _convert_to_hex(0, 3) -> '0000'
            _convert_to_hex(2.0, 3) -> '07D0'

        """
        temp_value = hex(int(10**decimal * float(value)))
        return ('0000' + str(temp_value)[2:].upper())[-4:]

    @staticmethod
    def _get_scale_hex(num, corr):
        """Gets the exponent in scientific notation."""
        expo = int(str(num * 10**40 + 0.01).split('+')[1]) - 40
        digits = round(num * 10**(-expo + 4))

        expo_hex = str(hex(corr - expo))[2:]
        digits_hex = ('00000' + str(hex(digits))[2:])[-5:]

        return expo_hex + digits_hex

    ######################################################################
    # Main Processes
    ######################################################################

    def set_direction(self, direction):
        """Sets the direction if the CHWP.

        Modifies the ``direction`` attribute.

        Command messages:
            W024XXXXX:
            - W: write type command
            - 02: target pid 2 setpoint
            - 4: decimal point format X.XXX
            - XXXXX: write value

        Args:
            direction (int): 0 for forward and 1 for backwards

        """
        if direction == '0':
            if self.verb:
                print('Forward')
            resp = self.send_message("*W02400000")
        elif direction == '1':
            if self.verb:
                print('Reverse')
            resp = self.send_message("*W02401388")

        if self.verb:
            print(self.return_messages([resp])[0])

    def declare_freq(self, freq):
        """Declare to memory what the CHWP frequency should be.

        **Note:** Does not actually change the frequency.

        Args:
            freq (float): Set freqency in Hz. Must be less than 3.5.

        """
        if float(freq) <= 3.5:
            self.hex_freq = '0' + self._convert_to_hex(freq, 3)
            if self.verb:
                print('Frequency Setpoint = ' + str(freq) + ' Hz')
        else:
            if self.verb:
                print('Invalid Frequency')

    def tune_stop(self):
        """Set the setpoint to 0 Hz and stop the CHWP.

        Command messages:
            W0C83:
            - W: write type command
            - 0C: target pid 1 action type
            - 83: set action type to direct
            W01400000
            - W: write type command
            - 01: target pid 1 setpoint
            - 4: decimal point format X.XXX
            - 00000: write value
            R01:
            - R: read type command
            - 01: target pid 1 setpoint
            Z02:
            - Z: reset type command
            - 02: target entire controller

        """
        if self.verb:
            print('Starting Stop')

        responses = []
        responses.append(self.send_message("*W0C83"))
        responses.append(self.send_message("*W01400000"))
        responses.append(self.send_message("*R01"))
        responses.append(self.send_message("*Z02"))
        if self.verb:
            print(responses)
            print(self.return_messages(responses))

        stop_params = [0.2, 0, 0]
        self.set_pid(stop_params)

    def tune_freq(self):
        """Set the setpoint to currently declared frequency.

        To declare the frequency, use ``PID.declare_freq()``.

        Command messages:
            W0C81:
            - W: write type command
            - 0C: target pid 1 action type
            - 81: set action type to reverse
            W014XXXXX
            - W: write type command
            - 01: target pid 1 setpoint
            - 4: decimal point format X.XXX
            - XXXXX: write value
            R01:
            - R: read type command
            - 01: target pid 1 setpoint
            Z02:
            - Z: reset type command
            - 02: target entire controller

        """
        if self.verb:
            print('Starting Tune')

        responses = []
        responses.append(self.send_message("*W0C81"))
        responses.append(self.send_message(f"*W014{self.hex_freq}"))
        responses.append(self.send_message("*R01"))
        responses.append(self.send_message("*Z02"))
        if self.verb:
            print(responses)
            print(self.return_messages(responses))

        tune_params = [0.2, 63, 0]
        self.set_pid(tune_params)

    @retry_multiple_times(loops=3)
    def get_freq(self):
        """Returns the current frequency of the CHWP.

        Command messages:
            X01:
            - X: read (decimal) type command
            - 01: target pid 1 value

        """
        if self.verb:
            print('Finding CHWP Frequency')

        responses = []
        responses.append(self.send_message("*X01"))
        decoded_resp = self.return_messages(responses)[0]
        if self.verb:
            print(responses)
            print(decoded_resp)
        if decoded_resp.msg_type == 'measure':
            return decoded_resp
        elif decoded_resp.msg_type == 'error':
            print(f"Error reading freq: {decoded_resp.msg}")
            raise ValueError
        else:
            print("Unknown freq response")
            raise ValueError

    @retry_multiple_times(loops=3)
    def get_target(self):
        """Returns the target frequency of the CHWP.

        Command messages:
            R01:
            - R: read type command
            - 01: target pid 1 setpoint

        """
        if self.verb:
            print('Finding target CHWP Frequency')

        responses = []
        responses.append(self.send_message("*R01"))
        decoded_resp = self.return_messages(responses)[0]
        if self.verb:
            print(responses)
            print(decoded_resp)
        if decoded_resp.msg_type == 'read':
            return decoded_resp
        elif decoded_resp.msg_type == 'error':
            print(f"Error reading target: {decoded_resp.msg}")
            raise ValueError
        else:
            print('Unknown target response')
            raise ValueError

    @retry_multiple_times(loops=3)
    def get_direction(self):
        """Get the current rotation direction.

        Returns:
            int: 0 for forward and 1 for backwards

        Command messages:
            R02:
            - R: read type command
            - 02: target pid 2 setpoint

        """
        if self.verb:
            print('Finding CHWP Direction')

        responses = []
        responses.append(self.send_message("*R02"))
        decoded_resp = self.return_messages(responses)[0]
        if self.verb:
            print(responses)
            print(decoded_resp)
        if decoded_resp.msg_type == 'read':
            return decoded_resp
        elif decoded_resp.msg_type == 'error':
            print(f"Error reading direction: {decoded_resp.msg}")
            raise ValueError
        else:
            print('Unknown direction response')
            raise ValueError

    def set_pid(self, params):
        """Sets the PID parameters of the controller.

        Command messages:
            W17XXXX
            - W: write type command
            - 17: target pid 1 p param
            - XXXX: write value
            W18XXXX
            - W: write type command
            - 18: target pid 1 i param
            - XXXX: write value
            W19XXXX
            - W: write type command
            - 19: target pid 1 d param
            - XXXX: write value
            Z02:
            - Z: reset type command
            - 02: target entire controller

        """
        if self.verb:
            print('Setting PID Params')

        p_value = self._convert_to_hex(params[0], 3)
        i_value = self._convert_to_hex(params[1], 0)
        d_value = self._convert_to_hex(params[2], 1)

        responses = []
        responses.append(self.send_message(f"*W17{p_value}"))
        responses.append(self.send_message(f"*W18{i_value}"))
        responses.append(self.send_message(f"*W19{d_value}"))
        responses.append(self.send_message("*Z02"))
        time.sleep(2)
        if self.verb:
            print(responses)
            print(self.return_messages(responses))

    def set_scale(self, slope, offset):
        """Set the conversion between feedback voltage and approximate
        frequency.

        Command messages:
            W14XXXXX:
            - W: write type command
            - 14: target feedback scale
            - XXXXX: write value
            W03XXXXX:
            - W: write type command
            - 03: target feedback offset
            - XXXXX: write value
            Z02:
            - Z: reset type command
            - 02: target entire controller

        """
        slope_hex = self._get_scale_hex(slope, 1)
        offset_hex = self._get_scale_hex(offset, 2)

        responses = []
        responses.append(self.send_message(f"*W14{slope_hex}"))
        responses.append(self.send_message(f"*W03{offset_hex}"))
        responses.append(self.send_message("*Z02"))
        if self.verb:
            print(responses)
            print(self.return_messages(responses))

    ######################################################################
    # Messaging
    ######################################################################

    def send_message(self, msg):
        """Send message over TCP to the PID controller.

        Args:
            msg (str): Command to send to the controller.

        Returns:
            str: Response from the controller.

        """
        for attempt in range(2):
            try:
                self.conn.sendall((msg + '\r\n').encode())
                time.sleep(0.5)  # Don't send messages too quickly
                data = self.conn.recv(4096).decode().strip()
                return data
            except (socket.timeout, OSError):
                print("Caught timeout waiting for response from PID controller. "
                      + "Trying again...")
                time.sleep(1)
                if attempt == 1:
                    print("Resetting connection")
                    self.conn.close()
                    self.conn = self._establish_connection(self.ip, int(self.port))
                    return self.send_message(msg)

    def return_messages(self, msg):
        """Decode list of responses from PID controller and return useful
        values.

        Args:
            msg (list): List of messages to decode.

        Returns:
            list: DecodedResponse

        """
        return self._decode_array(msg)

    @staticmethod
    def _decode_array(input_array):
        """Helper function to parse the individual response strings.

        Each function calls a series of commands which each have a reponse string.
        The strings are arranged into an array and sent here to be decoded. For each
        individual string, the first character is the action type:
            - R: read (hex)
            - W: write (hex)
            - E: enable
            - D: disable
            - P: put
            - G: get
            - X: read (decimal)
            - Z: reset
        Following the action type, the next two characters are the command type. The
        supported command type depends on the action type:
            - R01: read setpoint for pid 1 (rotation frequency setpoint)
            - R02: read setpoint for pid 2 (rotation direction setpoint)
            - W01: write setpoint for pid 1 (rotation frequency setpoint)
            - W02: write setpoint for pid 2 (rotation direction setpoint)
            - W0C: write action type for pid 1 (how to interpret sign of (setpoint-value))
            - X01: read value for pid 1 (current rotation frequency)
        "?" character indicates the error messages.
        The helper function goes through the raw response strings and replaces them
        with their decoded values.

        Args:
            input_array (list): List of str messages to decode

        Returns:
            list: DecodedResponse

        """
        output_array = list(input_array)

        for index, string in enumerate(list(input_array)):
            if not isinstance(string, str):
                output_array[index] = DecodedResponse(msg_type='error', msg='Unrecognized response')
                continue
            header = string[0]
            if '?' in string:
                output_array[index] = PID._decode_error(string)
            elif header == 'R':
                output_array[index] = PID._decode_read(string)
            elif header == 'W':
                output_array[index] = PID._decode_write(string)
            elif header == 'E':
                output_array[index] = DecodedResponse(msg_type='enable', msg='PID Enabled')
            elif header == 'D':
                output_array[index] = DecodedResponse(msg_type='disable', msg='PID Disabled')
            elif header == 'P':
                pass
            elif header == 'G':
                pass
            elif header == 'X':
                output_array[index] = PID._decode_measure(string)
            elif header == 'Z':
                output_array[index] = DecodedResponse(msg_type='reset', msg='PID Reset')
            else:
                output_array[index] = DecodedResponse(msg_type='error', msg='Unrecognized response')

        return output_array

    @staticmethod
    def _decode_error(string):
        """Helper function to decode error messages

        Args:
            string (str): Error message type string to decode

        Returns:
            DecodedResponse

        """
        if '?+9999.' in string:
            return DecodedResponse(msg_type='error', msg='Exceed Maximum Error')
        elif '?43' in string:
            return DecodedResponse(msg_type='error', msg='Command Error')
        elif '?46' in string:
            return DecodedResponse(msg_type='error', msg='Format Error')
        elif '?50' in string:
            return DecodedResponse(msg_type='error', msg='Parity Error')
        elif '?56' in string:
            return DecodedResponse(msg_type='error', msg='Serial Device Address Error')
        else:
            return DecodedResponse(msg_type='error', msg='Unrecognized Error')

    @staticmethod
    def _decode_read(string):
        """Helper function to decode "read (hex)" type response strings

        Specific decoding procedure depends on response string type:
            - R01 (pid 1 setpoint): convert hex value into decimal (X.XXX format).
                                    Returns decimal value
            - R02 (pid 2 setpoint): convert hex value into decimal (X.XXX format)
                                    and compair to mean value to determine rotation
                                    direction. Returns rotation direction

        Examples:
            _decode_read('R01400000') -> 0.0
            _decode_read('R014007D0') -> 2.0
            _decode_read('R02400000') -> 0
            _decode_read('R024007D0') -> 1

        Args:
            string (str): Read (hex) type string to decode

        Returns:
            DecodedResponse

        """
        end_string = string.split('\r')[-1]
        read_type = end_string[1:3]
        if len(end_string) != 9:
            return DecodedResponse(msg_type='error', msg='Unrecognized Read Length')
        # Decode target
        if read_type == '01':
            target = float(int(end_string[4:], 16) / 1000.)
            return DecodedResponse(msg_type='read', msg='Setpoint = ' + str(target), measure=target)
        # Decode direction
        elif read_type == '02':
            if int(end_string[4:], 16) / 1000. > 2.5:
                return DecodedResponse(msg_type='read', msg='Direction = Reverse', measure=1)
            else:
                return DecodedResponse(msg_type='read', msg='Direction = Forward', measure=0)
        else:
            return DecodedResponse(msg_type='error', msg='Unrecognized Read Type')

    @staticmethod
    def _decode_write(string):
        """Helper function to decode "write (hex)" type response strings

        Args:
            string (str): Write (hex) type string to decode

        Returns:
            DecodedResponse

        """
        write_type = string[1:]
        if write_type == '01':
            return DecodedResponse(msg_type='write', msg='Changed Setpoint')
        elif write_type == '02':
            return DecodedResponse(msg_type='write', msg='Changed Direction')
        elif write_type == '0C':
            return DecodedResponse(msg_type='write', msg='Changed Action Type')
        elif write_type == '17':
            return DecodedResponse(msg_type='write', msg='Changed PID 1 P Param')
        elif write_type == '18':
            return DecodedResponse(msg_type='write', msg='Changed PID 1 I Param')
        elif write_type == '19':
            return DecodedResponse(msg_type='write', msg='Changed PID 1 D Param')
        else:
            return DecodedResponse(msg_type='error', msg='Unrecognized Write')

    @staticmethod
    def _decode_measure(string):
        """Helper function to decode "read (decimal)" type response strings

        Deconding is done in the following way
            - X01 (pid 1 value): removes header and returns decimal value

        Args:
            string (str): Read (decimal) type string to decode

        Return:
            DecodedReponse
        """
        end_string = string.split('\r')[-1]
        measure_type = end_string[1:3]
        if measure_type == '01':
            freq = float(end_string[3:])
            return DecodedResponse(msg_type='measure', msg='Current frequency = ' + str(freq), measure=freq)
        else:
            return DecodedResponse(msg_type='error', msg='Unrecognized Measure')
