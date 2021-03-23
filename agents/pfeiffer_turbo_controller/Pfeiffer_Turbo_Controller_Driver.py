#Author: Michael Randall
#Email: mrandall@ucsd.edu

#This Driver works by creating a TCP connection to a Moxa Ethernet to Serial Converter.
#It uses this Converter to send and receive serial messages with the Pfeiffer Vacuum controller.
#The Driver employs the serial package to creat the TCP connection
#It also uses a slightly modified version of a Pfeiffer Vacuum Protocol package found on GitHub

import serial
import Pfeiffer_Vacuum_Protocol as PVP

class Pfeiffer_Turbo_Controller():
    
    def __init__(self, moxa_ip_address, moxa_port, turbo_address):
        """Initiates a TCP connection with the Moxa serial to ethernet converter to send serial communications.
        
        parameters: 
            (str) moxa_ip_address: The IP address of the moxa box
            (int) moxa_port: The port number of the Moxa box that the turbo is connected to.
                (e.g. 4001 for the first port)
            (int) turbo_address: The serial address of the turbo controller (e.g. 94)
                Check the turbo for the address.
                
        class variables:
            session: The TCP connection with the Moxa used to send and receive communication.
            (int) turbo_address: The serial Address of the Turbo Controller. 
        """
        
        self.session = serial.serial_for_url('socket://{}:{}'.format(moxa_ip_address, moxa_port),
                                        baudrate=9600,
                                        bytesize=serial.EIGHTBITS,
                                        parity=serial.PARITY_NONE,
                                        stopbits=serial.STOPBITS_ONE,
                                        timeout=3)
        
        self.turbo_address = turbo_address
        
        
    def get_turbo_motor_temperature(self):
        """Gets the temperatures of the turbo rotor from the turbo controller.
        
        parameters: 
            None
            
        returns:
            (int) rotor_temp: The rotor temperature of the turbo in Celsius.
        """
        
        PVP._send_data_request(self.session, self.turbo_address, 346)
        addr, rw, param_num, motor_temp = PVP._read_gauge_response(self.session)
        
        return int(motor_temp)
    
    
    def get_turbo_actual_rotation_speed(self):
        """Gets the current rotation speed of the turbo from the turbo controller.
        
        parameters: 
            None
            
        returns:
            (int) actual_rotation_speed: The current rotation speed of the turbo in Hz.
        """
        
        PVP._send_data_request(self.session, self.turbo_address, 309)
        
        addr, rw, param_num, actual_rotation_speed = PVP._read_gauge_response(self.session)
        
        return int(actual_rotation_speed)
    
    
    def get_turbo_set_rotation_speed(self):
        """Gets the the rotation speed that the turbo is set to from the turbo controller.
            This is the speed in Hz that the turbo motor will spin up to if turned on.
        
        parameters: 
            None
            
        returns:
            (int) set_rotation_speed: The rotation speed that the turbo is set to in Hz
        """
        
        PVP._send_data_request(self.session, self.turbo_address, 308)
        
        addr, rw, param_num, set_rotation_speed = PVP._read_gauge_response(self.session)
        
        return int(set_rotation_speed)
    
    
    def get_turbo_error_code(self):
        """Gets the current error code of the turbo from the turbo controller.
        
        parameters: 
            None
            
        returns:
            (int) error_code: the current error code of the turbo.
        """
        PVP._send_data_request(self.session, self.turbo_address, 303)
        
        
        addr, rw, param_num, error_code = PVP._read_gauge_response(self.session)
        
        return int(error_code)
    
    def unready_turbo(self):
        """Unreadies the turbo. Does not cause the turbo to spin up.
        
        parameters: 
            None
            
        returns:
            (bool) turbo_response: True for successful, False for failure.
        """
        
        PVP._send_control_command(self.session, self.turbo_address, 10, "000000")
        
        addr, rw, param_num, turbo_response = PVP._read_gauge_response(self.session)
        
        return turbo_response
    
    
    def ready_turbo(self):
        """Readies the turbo for spinning. Does not cause the turbo to spin up.
        
        parameters: 
            None
            
        returns:
            (bool) turbo_response: True for successful, False for failure.
        """
        
        PVP._send_control_command(self.session, self.turbo_address, 10, "111111")
        
        addr, rw, param_num, turbo_response = PVP._read_gauge_response(self.session)
        
        return turbo_response
    
    
    def turn_turbo_motor_on(self):
        """Turns the turbo motor on. The turbo must be readied before the motor will turn on.
            This is what causes the turbo to actually spin up.
        
        parameters: 
            None
            
        returns:
            (bool) turbo_response: True for successful, False for failure.
        """
        
        PVP._send_control_command(self.session, self.turbo_address, 23, "111111")
        
        addr, rw, param_num, turbo_response = PVP._read_gauge_response(self.session)
        
        return turbo_response
    
    
    def turn_turbo_motor_off(self):
        """Turns the turbo motor off.
        
        parameters: 
            None
            
        returns:
            (bool) turbo_response: True for successful, False for failure.
        """
        
        PVP._send_control_command(self.session, self.turbo_address, 23, "000000")
        
        addr, rw, param_num, turbo_response = PVP._read_gauge_response(self.session)
        
        return turbo_response
    
    
    def acknowledge_turbo_errors(self):
        """Acknowledges the turbo errors. This is analagous to clearing the errors.
            If the errors were fixed, the turbo will turn back on.
        
        parameters: 
            None
            
        returns:
            (bool) turbo_response: True for successful, False for failure.
        """
        
        PVP._send_control_command(self.session, self.turbo_address, 9, "111111")
        
        addr, rw, param_num, turbo_response = PVP._read_gauge_response(self.session)
        
        return turbo_response
    


