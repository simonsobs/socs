from serial import Serial
import time
import struct
import array as arr


# some commands require a CRC code (cyclic redundancy check) -
# these require the provided CRC table
crc_table = arr.array('H', [
    0x0,     0x1021,  0x2042,  0x3063,  0x4084,  0x50a5,  0x60c6,  0x70e7,
    0x8108,  0x9129,  0xa14a,  0xb16b,  0xc18c,  0xd1ad,  0xe1ce,  0xf1ef,
    0x1231,  0x210,   0x3273,  0x2252,  0x52b5,  0x4294,  0x72f7,  0x62d6,
    0x9339,  0x8318,  0xb37b,  0xa35a,  0xd3bd,  0xc39c,  0xf3ff,  0xe3de,
    0x2462,  0x3443,  0x420,   0x1401,  0x64e6,  0x74c7,  0x44a4,  0x5485,
    0xa56a,  0xb54b,  0x8528,  0x9509,  0xe5ee,  0xf5cf,  0xc5ac,  0xd58d,
    0x3653,  0x2672,  0x1611,  0x630,   0x76d7,  0x66f6,  0x5695,  0x46b4,
    0xb75b,  0xa77a,  0x9719,  0x8738,  0xf7df,  0xe7fe,  0xd79d,  0xc7bc,
    0x48c4,  0x58e5,  0x6886,  0x78a7,  0x840,   0x1861,  0x2802,  0x3823,
    0xc9cc,  0xd9ed,  0xe98e,  0xf9af,  0x8948,  0x9969,  0xa90a,  0xb92b,
    0x5af5,  0x4ad4,  0x7ab7,  0x6a96,  0x1a71,  0xa50,   0x3a33,  0x2a12,
    0xdbfd,  0xcbdc,  0xfbbf,  0xeb9e,  0x9b79,  0x8b58,  0xbb3b,  0xab1a,
    0x6ca6,  0x7c87,  0x4ce4,  0x5cc5,  0x2c22,  0x3c03,  0xc60,   0x1c41,
    0xedae,  0xfd8f,  0xcdec,  0xddcd,  0xad2a,  0xbd0b,  0x8d68,  0x9d49,
    0x7e97,  0x6eb6,  0x5ed5,  0x4ef4,  0x3e13,  0x2e32,  0x1e51,  0xe70,
    0xff9f,  0xefbe,  0xdfdd,  0xcffc,  0xbf1b,  0xaf3a,  0x9f59,  0x8f78,
    0x9188,  0x81a9,  0xb1ca,  0xa1eb,  0xd10c,  0xc12d,  0xf14e,  0xe16f,
    0x1080,  0xa1,    0x30c2,  0x20e3,  0x5004,  0x4025,  0x7046,  0x6067,
    0x83b9,  0x9398,  0xa3fb,  0xb3da,  0xc33d,  0xd31c,  0xe37f,  0xf35e,
    0x2b1,   0x1290,  0x22f3,  0x32d2,  0x4235,  0x5214,  0x6277,  0x7256,
    0xb5ea,  0xa5cb,  0x95a8,  0x8589,  0xf56e,  0xe54f,  0xd52c,  0xc50d,
    0x34e2,  0x24c3,  0x14a0,  0x481,   0x7466,  0x6447,  0x5424,  0x4405,
    0xa7db,  0xb7fa,  0x8799,  0x97b8,  0xe75f,  0xf77e,  0xc71d,  0xd73c,
    0x26d3,  0x36f2,  0x691,   0x16b0,  0x6657,  0x7676,  0x4615,  0x5634,
    0xd94c,  0xc96d,  0xf90e,  0xe92f,  0x99c8,  0x89e9,  0xb98a,  0xa9ab,
    0x5844,  0x4865,  0x7806,  0x6827,  0x18c0,  0x8e1,   0x3882,  0x28a3,
    0xcb7d,  0xdb5c,  0xeb3f,  0xfb1e,  0x8bf9,  0x9bd8,  0xabbb,  0xbb9a,
    0x4a75,  0x5a54,  0x6a37,  0x7a16,  0xaf1,   0x1ad0,  0x2ab3,  0x3a92,
    0xfd2e,  0xed0f,  0xdd6c,  0xcd4d,  0xbdaa,  0xad8b,  0x9de8,  0x8dc9,
    0x7c26,  0x6c07,  0x5c64,  0x4c45,  0x3ca2,  0x2c83,  0x1ce0,  0xcc1,
    0xef1f,  0xff3e,  0xcf5d,  0xdf7c,  0xaf9b,  0xbfba,  0x8fd9,  0x9ff8,
    0x6e17,  0x7e36,  0x4e55,  0x5e74,  0x2e93,  0x3eb2,  0xed1,   0x1ef0
])


def calc_crc(data):
    """
        Calculates CRC
    """

    crc = 0
    for i in data:
        crc = crc_table[(crc >> 8) ^ i] ^ (crc << 8)
        crc = crc % 65536
    return crc


class VantagePro2:
    """
        Allows communication to Vantage Pro 2 Weather Monitor Module.
        Contains commands to be issued and member variables that store
        collected data.
    """

    def __init__(self, path, baud=19200, timeout=1):
        """
            Establish serial connection and initialize member variables
        """

        if not path:
            path = '/dev/ttyUSB0'
        self.com = Serial(port=path, baudrate=baud, timeout=timeout)
        self.startup()

    def startup(self):
        """
            Wakeup vantage pro 2 console
        """
        self.com.write(b"\n")
        for i in range(0, 3):
            response = self.com.read(2)
            if response == b'\n\r':
                break
            time.sleep(1.2)
        else:
            raise TimeoutError("Vantage Pro 2 console not woke")

    def crc_check(self, data):
        """
        Checks received data. If received data has a CRC value of 0,
        then correct message received!
        """

        crc = calc_crc(data)
        if crc != 0:
            print('Failed CRC. Errors in data received')

    def close(self):
        self.com.close()

    # closing serial if agent goes out of scope

    def __exit__(self):
        self.com.close()

    def conditions_screen(self):
        """
            Move console to conditions screen
            (where loop command can succesfully be sent)
        """

        self.startup()
        self.com.write(b'RXTEST\n')
        time.sleep(2)

        # reads response from console
        for i in range(0, 3):
            ok = self.com.read(6)
            if ok == b'\n\rOK\n\r':
                break
        else:
            raise TimeoutError("Command not acknowledged")

    def msg(self, msg):
        """
            Send general command or query to module.
            If command received and acknowledged, continue
            else retry 2 more times.
        """

        attempt = 0
        while attempt < 3:
            self.startup()
            self.com.write(bytes(msg, 'ascii'))
            time.sleep(0.1)
            ack = 0
            for i in range(0, 3):
                ack = self.com.read(1)
                if ack == b'\x06':
                    return True
            attempt += 1
        else:
            return False

    def interrupt_daq(self):
        """
            Interrupts loop command...if sent before loop command finishes
        """

        self.startup()
        self.com.write(b'\n')
        for i in range(0, 3):
            response = self.com.read(2)
            if response == b'\n\r':
                print("Data Acquisition succesfully interrupted")
                break
            time.sleep(0.1)
        else:
            raise TimeoutError('Data Acquisition not interrupted')

    def receive_data(self):
        """
            Reads weather data from console and returns loop_data{}
            User should read Vantage Pro Serial Communication Reference Manual
            for the format of the loop data packet.
            Specifically for units of data!

            -Barometer trend: the current 3 hour barometer trend.
                    -60 = Falling rapidly
                    -20 = Falling slowly
                    0 = Steady
                    20 = Rising slowly
                    60 = Rising rapidly
                    80 = No trend available
                    Any other value = The VantagePro2 does not have the 3 hours
                    of data needed to determine the barometer trend.
            -Barometer: Current barometer reading (Hg/1000)
            -Inside Temperature: Temperatue in Fahrenheit (10th of a degree)
            -Inside Humidity: Relative humidity in percent
            -Outside Temperature: Temperature in Fahrenheit (10th of a degree)
            -Wind Speed: Wind speed in miles per hour
            -10 min average wind speed: 10 minute average wind speed in mph
            -Wind Direction: From 1-360 degrees
                    0 = No wind direction data
                    90 = East
                    180 = South
                    270 = West
                    360 = North
            Extra Temperatures: Temperature from up to 7 extra temperature
                stations.
            Soil Temperatures: Four soil temperature sensors, in the same
                format as the extra temperatures format listed above.
            Leaf Temperatures: Four leaf temperature sensors, in the same
                format as the extra temperatures format listed above.
            Outside Humidity: Relativie humidity in percent
            Extra Humidities: Realtive humidity in percent for 7 humidity
                 stations
            Rain Rate: Number of rain clicks (0.1in or 0.2mm) per hour
            UV: "Unit is in UV index"
            Solar Radiation: Units in watt/meter^2
            Storm Rain: Stored in 100th of an inch
            Start Date of Current storm: Gives month, date,
                and year (offset by 2000)
            Day Rain: Number of rain clicks (0.1in or 0.2mm)/hour
                in the past day
            Month Rain: Number of rain clicks (0.1in or 0.2mm)/hour
                in the past month
            Year Rain: Number of rain clicks (0.1in or 0.2mm)/hour
                in the past year
            Day ET: 1000th of an inch
            Month ET: 1000th of an inch
            Year ET: 1000th of an inch
            Soil Moistures: In centibar, supports 4 soil sensors
            Leaf Wetnesses: Scale from 0-15. Supports 4 leaf sensors
                    0 = Very dry
                    15 = Very wet
            Inside Alarms: Currently active inside alarms
            Rain Alarms: Currently active rain alarms
            Outside Alarms: Currently active outside alarms
            Outside Humidity Alarms: Currently active humidity alarms
            Extra Temp/Hum Alarms: Currently active extra
                temperature/humidity alarms
            Soil & Leaf Alarms: Currently active soil/leaf alarms
            Console Battery Voltage: Voltage
            Time of Sunrise: Time is stored as hour x 100 + min
            Time of Sunset: Time is stored as hour x 100 + min

        """

        info = b''

        # Give device multiple chances to send its data
        for i in range(0, 3):
            info = self.com.read(99)
            if info:
                break
            else:
                time.sleep(0.5)
        else:
            raise TimeoutError("Timeout error: no data from LOOP command")

        loop_data = {}
        byte_data = struct.unpack('=5b3h1b1h2B1H23b1h1b9h25b1h2b2h2c1h', info)
        loop_data['bar_trend'] = byte_data[3]
        loop_data['packet_type'] = byte_data[4]
        loop_data['next_record'] = byte_data[5]
        loop_data['barometer'] = byte_data[6] / 1000.0
        loop_data['temp_inside'] = byte_data[7] / 10.0
        loop_data['humidity_inside'] = byte_data[8]
        loop_data['temp_outside'] = byte_data[9] / 10.0
        loop_data['wind_speed'] = byte_data[10]
        loop_data['avg_wind_speed'] = byte_data[11]
        loop_data['wind_dir'] = byte_data[12]
        loop_data['extra_temp0'] = byte_data[13] - 90.0
        loop_data['extra_temp1'] = byte_data[14] - 90.0
        loop_data['extra_temp2'] = byte_data[15] - 90.0
        loop_data['extra_temp3'] = byte_data[16] - 90.0
        loop_data['extra_temp4'] = byte_data[17] - 90.0
        loop_data['extra_temp5'] = byte_data[18] - 90.0
        loop_data['extra_temp6'] = byte_data[19] - 90.0
        loop_data['soil_temp0'] = byte_data[20] - 90.0
        loop_data['soil_temp1'] = byte_data[21] - 90.0
        loop_data['soil_temp2'] = byte_data[22] - 90.0
        loop_data['soil_temp3'] = byte_data[23] - 90.0
        loop_data['leaf_temp0'] = byte_data[24] - 90.0
        loop_data['leaf_temp1'] = byte_data[25] - 90.0
        loop_data['leaf_temp2'] = byte_data[26] - 90.0
        loop_data['leaf_temp3'] = byte_data[27] - 90.0
        loop_data['humidity_outside'] = byte_data[28]
        loop_data['extra_hum0'] = byte_data[29]
        loop_data['extra_hum1'] = byte_data[30]
        loop_data['extra_hum2'] = byte_data[31]
        loop_data['extra_hum3'] = byte_data[32]
        loop_data['extra_hum4'] = byte_data[33]
        loop_data['extra_hum5'] = byte_data[34]
        loop_data['extra_hum6'] = byte_data[35]
        loop_data['rain_rate'] = byte_data[36]
        loop_data['UV'] = byte_data[37]
        loop_data['solar_rad'] = byte_data[38]
        loop_data['storm_rain'] = byte_data[39] / 100.0
        loop_data['storm_start'] = byte_data[40]
        loop_data['day_rain'] = byte_data[41]
        loop_data['month_rain'] = byte_data[42]
        loop_data['year_rain'] = byte_data[43]
        loop_data['day_ET'] = byte_data[44] / 1000.0
        loop_data['month_ET'] = byte_data[45] / 100.0
        loop_data['year_ET'] = byte_data[46] / 100.0
        loop_data['soil_moisture0'] = byte_data[47]
        loop_data['soil_moisture1'] = byte_data[48]
        loop_data['soil_moisture2'] = byte_data[49]
        loop_data['soil_moisture3'] = byte_data[50]
        loop_data['leaf_wetness0'] = byte_data[51]
        loop_data['leaf_wetness1'] = byte_data[52]
        loop_data['leaf_wetness2'] = byte_data[53]
        loop_data['leaf_wetness3'] = byte_data[54]
        loop_data['inside_alarm0'] = byte_data[55]
        loop_data['inside_alarm1'] = byte_data[56]
        loop_data['rain_alarm'] = byte_data[57]
        loop_data['outside_alarm0'] = byte_data[58]
        loop_data['outside_alarm1'] = byte_data[59]
        loop_data['extra_temp_hum_alarm0'] = byte_data[60]
        loop_data['extra_temp_hum_alarm1'] = byte_data[61]
        loop_data['extra_temp_hum_alarm2'] = byte_data[62]
        loop_data['extra_temp_hum_alarm3'] = byte_data[63]
        loop_data['extra_temp_hum_alarm4'] = byte_data[64]
        loop_data['extra_temp_hum_alarm5'] = byte_data[65]
        loop_data['extra_temp_hum_alarm6'] = byte_data[66]
        loop_data['soil_leaf_alarm0'] = byte_data[67]
        loop_data['soil_leaf_alarm1'] = byte_data[68]
        loop_data['soil_leaf_alarm2'] = byte_data[69]
        loop_data['soil_leaf_alarm3'] = byte_data[70]
        loop_data['transmitter_battery_status'] = byte_data[71]
        loop_data['console_battery_voltage'] = ((byte_data[72]*300)/512)/100.0
        loop_data['forecast_icons'] = byte_data[73]
        loop_data['forecast_rule_num'] = byte_data[74]
        loop_data['time_sunrise'] = byte_data[75]
        loop_data['time_sunset'] = byte_data[76]

        # CRC check, data must be sent byte by byte
        pure_data = struct.unpack('=99b', info)
        self.crc_check(pure_data)

        return loop_data

    def weather_daq(self):
        """
            Issues "LOOP 1"(which samples weather data) command
            to weather station, and unpacks the data.
        """

        # Startup and issue loop command
        self.startup()
        command = "LOOP 1\n"
        if not self.msg(command):
            print("message failed to be sent!")

        # collect data
        return self.receive_data()

    def print_data(self, data):
        """
            Prints contents of data collected from LOOP <loops> command.
            Loop: loop#
            Field : Value format.
        """

        print("**************")
        for i in data:
            print("{} : {}".format(i, data[i]))
