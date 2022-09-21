# Author: Michael Randall
# Email: mrandall@ucsd.edu

# This Driver works by creating a TCP connection to a Moxa Ethernet to Serial Converter.
# It uses this Converter to send and receive serial messages with the Pfeiffer Vacuum controller.
# The Driver employs the serial package to creat the TCP connection
# It also uses a slightly modified version of a Pfeiffer Vacuum Protocol package found on GitHub

import serial
from pfeiffer_vacuum_protocol.pfeiffer_vacuum_protocol import \
    _read_gauge_response as read_gauge_response
from pfeiffer_vacuum_protocol.pfeiffer_vacuum_protocol import \
    _send_control_command as send_control_command
from pfeiffer_vacuum_protocol.pfeiffer_vacuum_protocol import \
    _send_data_request as send_data_request

# Data type 0 from TC400 Manual Section 8.3 - Applied data types
PFEIFFER_BOOL = {'111111': True,
                 '000000': False}


class PfeifferTC400:
    """Initiates a TCP connection with the Moxa serial to ethernet converter to send serial communications.

    Parameters
    ----------
        moxa_ip_address: str
            The IP address of the moxa box
        moxa_port: int
            The port number of the Moxa box that the turbo is connected to.
            (e.g. 4001 for the first port)
        turbo_address: int
            The serial address of the turbo controller (e.g. 94)
            Check the turbo for the address.

    Attributes
    ----------
        ser: serial.Serial Object
            The TCP connection with the Moxa used to send and receive communication.
        turbo_address: int
            The serial Address of the Turbo Controller.
    """

    def __init__(self, moxa_ip_address, moxa_port, turbo_address):
        self.ser = serial.serial_for_url('socket://{}:{}'.format(moxa_ip_address, moxa_port),
                                         baudrate=9600,
                                         bytesize=serial.EIGHTBITS,
                                         parity=serial.PARITY_NONE,
                                         stopbits=serial.STOPBITS_ONE,
                                         timeout=3)

        self.turbo_address = turbo_address

    def get_turbo_motor_temperature(self):
        """Gets the temperatures of the turbo rotor from the turbo controller.

        Returns
        -------
        int
            The rotor temperature of the turbo in Celsius.
        """

        send_data_request(self.ser, self.turbo_address, 346)
        addr, rw, param_num, motor_temp = read_gauge_response(self.ser)

        return int(motor_temp)

    def get_turbo_actual_rotation_speed(self):
        """Gets the current rotation speed of the turbo from the turbo controller.

        Returns
        -------
        int
            The current rotation speed of the turbo in Hz.
        """

        send_data_request(self.ser, self.turbo_address, 309)

        addr, rw, param_num, actual_rotation_speed = read_gauge_response(self.ser)

        return int(actual_rotation_speed)

    def get_turbo_set_rotation_speed(self):
        """Gets the the rotation speed that the turbo is set to from the turbo controller.
        This is the speed in Hz that the turbo motor will spin up to if turned on.

        Returns
        -------
        int
            The rotation speed that the turbo is set to in Hz
        """

        send_data_request(self.ser, self.turbo_address, 308)

        addr, rw, param_num, set_rotation_speed = read_gauge_response(self.ser)

        return int(set_rotation_speed)

    def get_turbo_error_code(self):
        """Gets the current error code of the turbo from the turbo controller.

        Returns
        -------
        str
            The current error code of the turbo.
        """
        send_data_request(self.ser, self.turbo_address, 303)

        addr, rw, param_num, error_code = read_gauge_response(self.ser)

        return error_code

    def unready_turbo(self):
        """Unreadies the turbo. Does not cause the turbo to spin up.
        Returns
        -------
        bool
            True for successful, False for failure.
        """

        send_control_command(self.ser, self.turbo_address, 10, "000000")

        addr, rw, param_num, turbo_response = read_gauge_response(self.ser)

        if turbo_response not in PFEIFFER_BOOL:
            raise ValueError(f"Unrecognized response from turbo: {turbo_response}")
        else:
            return turbo_response == "111111"

    def ready_turbo(self):
        """Readies the turbo for spinning. Does not cause the turbo to spin up.

        Returns
        -------
        bool
            True for successful, False for failure.
        """

        send_control_command(self.ser, self.turbo_address, 10, "111111")

        addr, rw, param_num, turbo_response = read_gauge_response(self.ser)

        if turbo_response not in PFEIFFER_BOOL:
            raise ValueError(f"Unrecognized response from turbo: {turbo_response}")
        else:
            return turbo_response == "111111"

    def turn_turbo_motor_on(self):
        """Turns the turbo motor on. The turbo must be readied before the motor will turn on.
        This is what causes the turbo to actually spin up.

        Returns
        -------
        bool
            True for successful, False for failure.
        """

        send_control_command(self.ser, self.turbo_address, 23, "111111")

        addr, rw, param_num, turbo_response = read_gauge_response(self.ser)

        if turbo_response not in PFEIFFER_BOOL:
            raise ValueError(f"Unrecognized response from turbo: {turbo_response}")
        else:
            return turbo_response == "111111"

    def turn_turbo_motor_off(self):
        """Turns the turbo motor off.

        Returns
        -------
        bool
            True for successful, False for failure.
        """

        send_control_command(self.ser, self.turbo_address, 23, "000000")

        addr, rw, param_num, turbo_response = read_gauge_response(self.ser)

        if turbo_response not in PFEIFFER_BOOL:
            raise ValueError(f"Unrecognized response from turbo: {turbo_response}")
        else:
            return turbo_response == "111111"

    def acknowledge_turbo_errors(self):
        """Acknowledges the turbo errors. This is analagous to clearing the errors.
        If the errors were fixed, the turbo will be able to be turned back on.

        Returns
        -------
        bool
            True for successful, False for failure.
        """

        send_control_command(self.ser, self.turbo_address, 9, "111111")

        addr, rw, param_num, turbo_response = read_gauge_response(self.ser)

        if turbo_response not in PFEIFFER_BOOL:
            raise ValueError(f"Unrecognized response from turbo: {turbo_response}")
        else:
            return turbo_response == "111111"
