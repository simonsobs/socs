import socket
import time


class CO2:
    """Initiates a TCP connection with the Moxa serial to ethernet converter to send serial communications.

    Parameters
    ----------
        moxa_ip_address: str
            The IP address of the moxa box
        moxa_port: int
            The port number of the Moxa box that the turbo is connected to.
            (e.g. 4001 for the first port)

    Attributes
    ----------
        ser: serial.Serial Object
            The TCP connection with the Moxa used to send and receive communication.
    """

    def __init__(self, moxa_ip_address, moxa_port, turbo_address):
        self.ser = serial.serial_for_url('socket://{}:{}'.format(moxa_ip_address, moxa_port),
                                         baudrate=9600,
                                         bytesize=serial.EIGHTBITS,
                                         parity=serial.PARITY_NONE,
                                         timeout=10)

    def get_values(self):
         """Gets the values from the CO2 monitor.

        Returns
        -------
        list
            List of values: CO2 concentration, Air temp, Relative humidity, Dew point temp, Wet bulb temp
        """
        line1 = self.ser.readline().decode("utf-8")
        line2 = self.ser.readline().decode("utf-8")

        if line1[0] == '$':
            fields = line1.split(':')
            values = line2.split(':')
        else:
            fields = line2.split(':')
            values = line1.split(':')

        # print("Fields: ", fields)
        # print("Values: ", values)
        data = []
        data.append(values[0].split('C')[1].split('p')[0])
        data.append(values[1].split('T')[1].split('C')[0])
        data.append(values[2].split('H')[1].split('%')[0])
        data.append(values[3].split('d')[1].split('C')[0])
        data.append(values[4].split('w')[1].split('C')[0])
        # print("CO2 concentration: ", values[0].split('C')[1].split('p')[0], "ppm")
        # print("Air temp: ", values[1].split('T')[1].split('C')[0], "C")
        # print("Relative humidity: ", values[2].split('H')[1].split('%')[0], "%")
        # print("Dew point temp: ", values[3].split('d')[1].split('C')[0], "C")
        # print("Wet bulb temp: ", values[4].split('w')[1].split('C')[0], "C")

        return data