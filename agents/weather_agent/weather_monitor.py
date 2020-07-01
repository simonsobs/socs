from serial import Serial
import time
import struct
import os
from datetime import datetime
import array as arr
import types

BUFF_SIZE = 1024

class WeatherMonitor:
    """
        Allows communication to Vantage Pro 2 Weather Monitor Module.
        Contains commands to be issued and member variables that store collected data.
    """

    def __init__(self, path, baud=19200, timeout=1):
        """
            Establish serial connection and initialize member variables
        """       
        if not path:
            path = '/dev/ttyUSB0'
        self.com = Serial(port = path, baudrate=baud, timeout=timeout)
        self.startup()

        #some commands require a CRC code (cyclic redundancy check) - these require the provided CRC table
        self.crc_table = arr.array('H', [
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


    def calc_crc(self, data):
        """
            Calculates CRC
        """
        crc = 0
        for i in data:
            crc = self.crc_table[(crc >> 8) ^ i] ^ (crc << 8)
            crc = crc % 65536
        return crc

    
    def crc_check(self, data):
        """
        Checks received data. If received data has a CRC value of 0, then correct message received!
        """
        crc = self.calc_crc(data)
        if crc != 0:
            raise ValueError('Failed CRC. Errors in data received')


    def open_agent(self):
        self.com.open()


    def close(self):
        self.com.close()
        

    #closing serial if agent goes out of scope
    def __exit__(self):
        self.com.close()

    
    def conditions_screen(self):
        """
            Move console to conditions screen (where loop command can succesfully be sent)
        """
        self.startup()
        self.com.write(b'RXTEST\n')
        time.sleep(2)

        #reads response from console
        for i in range(0,3):
            ok = self.com.read(6)
            if ok == b'\n\rOK\n\r':
                break
        else:
            raise TimeoutError("Command not acknowledged")



    def msg(self, msg):
        """
            Send general command or query to module.
            If command received and acknowledged, continue
        """
        self.startup()
        self.com.write(bytes(msg, 'ascii'))
        time.sleep(0.1)
        for i in range(0,3):
            ack = self.com.read(1)
            if ack == b'\x06':
                break
        else:
            raise TimeoutError("Command not acknowledged")


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
            for the format of the loop data packet. Specifically for units of data!
        """

        info = b''
            
        # Give device multiple chances to send its data
        for i in range(0,3):
            info = self.com.read(99)
            if info:
                break
            else:
                time.sleep(0.5)
        else:
            raise TimeoutError("Timeout error: no data from LOOP command")

        loop_data = {
            'L' : 0, 'O' : 0, 'O1' : 0, 'bar_trend' : 0, 'packet_type' : 0, 'next_record' : 0, 'barometer' : 0, 'temp_inside' : 0, 
            'humidity_inside' : 0, 'temp_outside' : 0, 'wind_speed' : 0, 'avg_wind_speed' : 0, 'wind_dir' : 0, 'extra_temp0' : 0, 
            'extra_temp1' : 0, 'extra_temp2' : 0, 'extra_temp3' : 0, 'extra_temp4' : 0, 'extra_temp5' : 0, 'extra_temp6' : 0,
            'soil_temp0' : 0, 'soil_temp1' : 0, 'soil_temp2' : 0, 'soil_temp3' : 0, 'leaf_temp0' : 0, 'leaf_temp1' : 0, 
            'leaf_temp2' : 0, 'leaf_temp3' : 0, 'humidity_outside' : 0, 'extra_hum0' : 0, 'extra_hum1' : 0, 'extra_hum2' : 0, 
            'extra_hum3' : 0, 'extra_hum4' : 0, 'extra_hum5' : 0, 'extra_hum6' : 0, 'rain_rate' : 0, 'uv' : 0, 'solar_rad' : 0,
            'storm_rain' : 0, 'storm_start' : 0, 'day_rain' : 0, 'month_rain' : 0, 'year_rain' : 0, 'day_ET' : 0, 'month_ET' : 0, 
            'year_ET' : 0, 'soil_moisture0' : 0, 'soil_moisture1' : 0, 'soil_moisture2' : 0, 'soil_moisture3' : 0, 'leaf_wetness0' : 0, 
            'leaf_wetness1' : 0, 'leaf_wetness2' : 0, 'leaf_wetness3' : 0, 'inside_alarm0' : 0, 'inside_alarm1' : 0, 'rain_alarm' : 0,
            'outside_alarm0' : 0, 'outside_alarm1' : 0, 'extra_temp_hum_alarm0' : 0, 'extra_temp_hum_alarm1' : 0, 'extra_temp_hum_alarm2' : 0, 
            'extra_temp_hum_alarm3' : 0, 'extra_temp_hum_alarm4' : 0, 'extra_temp_hum_alarm5' : 0, 'extra_temp_hum_alarm6' : 0, 
            'soil_leaf_alarm0' : 0, 'soil_leaf_alarm1' : 0, 'soil_leaf_alarm2' : 0, 'soil_leaf_alarm3' : 0, 'transmitter_battery_status' : 0,
            'console_battery_voltage' : 0, 'forecast_icons' : 0, 'forecast_rule_num' : 0, 'time_sunrise' : 0, 'time_sunset' : 0
        }
        
        # loop_data[i]{field} = value
        byte_data = struct.unpack('=5b3h1b1h2B1H23b1h1b9h25b1h2b2h2c1h', info)
        loop_data['L']                          = int(byte_data[0])
        loop_data['O']                          = int(byte_data[1])
        loop_data['O1']                         = int(byte_data[2])
        loop_data['bar_trend']                  = int(byte_data[3])
        loop_data['packet_type']                = int(byte_data[4])
        loop_data['next_record']                = int(byte_data[5])
        loop_data['barometer']                  = float(byte_data[6] / 1000.0)
        loop_data['temp_inside']                = float(byte_data[7] / 10.0)
        loop_data['humidity_inside']            = float(byte_data[8])
        loop_data['temp_outside']               = float(byte_data[9] / 10.0)
        loop_data['wind_speed']                 = float(byte_data[10])
        loop_data['avg_wind_speed']             = float(byte_data[11])
        loop_data['wind_dir']                   = int(byte_data[12])
        loop_data['extra_temp0']                = float(byte_data[13]) - 90.0
        loop_data['extra_temp1']                = float(byte_data[14]) - 90.0
        loop_data['extra_temp2']                = float(byte_data[15]) - 90.0
        loop_data['extra_temp3']                = float(byte_data[16]) - 90.0
        loop_data['extra_temp4']                = float(byte_data[17]) - 90.0
        loop_data['extra_temp5']                = float(byte_data[18]) - 90.0
        loop_data['extra_temp6']                = float(byte_data[19]) - 90.0
        loop_data['soil_temp0']                 = float(byte_data[20]) - 90.0
        loop_data['soil_temp1']                 = float(byte_data[21]) - 90.0
        loop_data['soil_temp2']                 = float(byte_data[22]) - 90.0
        loop_data['soil_temp3']                 = float(byte_data[23]) - 90.0
        loop_data['leaf_temp0']                 = float(byte_data[24]) - 90.0
        loop_data['leaf_temp1']                 = float(byte_data[25]) - 90.0
        loop_data['leaf_temp2']                 = float(byte_data[26]) - 90.0
        loop_data['leaf_temp3']                 = float(byte_data[27]) - 90.0
        loop_data['humidity_outside']           = float(byte_data[28])
        loop_data['extra_hum0']                 = float(byte_data[29])
        loop_data['extra_hum1']                 = float(byte_data[30])
        loop_data['extra_hum2']                 = float(byte_data[31])
        loop_data['extra_hum3']                 = float(byte_data[32])
        loop_data['extra_hum4']                 = float(byte_data[33])
        loop_data['extra_hum5']                 = float(byte_data[34])
        loop_data['extra_hum6']                 = float(byte_data[35])
        loop_data['rain_rate']                  = float(byte_data[36]) 
        loop_data['uv']                         = float(byte_data[37])
        loop_data['solar_rad']                  = float(byte_data[38])
        loop_data['storm_rain']                 = float(byte_data[39]) / 100.0
        loop_data['storm_start']                = float(byte_data[40])
        loop_data['day_rain']                   = float(byte_data[41])
        loop_data['month_rain']                 = float(byte_data[42])
        loop_data['year_rain']                  = float(byte_data[43])
        loop_data['day_ET']                     = float(byte_data[44]) / 1000.0
        loop_data['month_ET']                   = float(byte_data[45]) / 100.0
        loop_data['year_ET']                    = float(byte_data[46]) / 100.0
        loop_data['soil_moisture0']             = float(byte_data[47])
        loop_data['soil_moisture1']             = float(byte_data[48])
        loop_data['soil_moisture2']             = float(byte_data[49])
        loop_data['soil_moisture3']             = float(byte_data[50])
        loop_data['leaf_wetness0']              = int(byte_data[51])
        loop_data['leaf_wetness1']              = int(byte_data[52])
        loop_data['leaf_wetness2']              = int(byte_data[53])
        loop_data['leaf_wetness3']              = int(byte_data[54])
        loop_data['inside_alarm0']              = float(byte_data[55])
        loop_data['inside_alarm1']              = float(byte_data[56])
        loop_data['rain_alarm']                 = float(byte_data[57])
        loop_data['outside_alarm0']             = float(byte_data[58])
        loop_data['outside_alarm1']             = float(byte_data[59])
        loop_data['extra_temp_hum_alarm0']      = float(byte_data[60])
        loop_data['extra_temp_hum_alarm1']      = float(byte_data[61])
        loop_data['extra_temp_hum_alarm2']      = float(byte_data[62])
        loop_data['extra_temp_hum_alarm3']      = float(byte_data[63])
        loop_data['extra_temp_hum_alarm4']      = float(byte_data[64])
        loop_data['extra_temp_hum_alarm5']      = float(byte_data[65])
        loop_data['extra_temp_hum_alarm6']      = float(byte_data[66])
        loop_data['soil_leaf_alarm0']           = float(byte_data[67])
        loop_data['soil_leaf_alarm1']           = float(byte_data[68])
        loop_data['soil_leaf_alarm2']           = float(byte_data[69])
        loop_data['soil_leaf_alarm3']           = float(byte_data[70])
        loop_data['transmitter_battery_status'] = float(byte_data[71])
        loop_data['console_battery_voltage']    = ((float(byte_data[72] * 300) / 512) / 100.0)
        loop_data['forecast_icons']             = int(byte_data[73])
        loop_data['forecast_rule_num']          = int(byte_data[74])
        loop_data['time_sunrise']               = float(byte_data[75])
        loop_data['time_sunset']                = float(byte_data[76])
        
        # CRC check, data must be sent byte by byte
        pure_data = struct.unpack('=99b', info)
        self.crc_check(pure_data)

        return loop_data
        

    def weather_daq(self, loops):
        """
            Issues "LOOP <loops>" command to weather station, and unpacks/stores
            the data to daq[{}]. Each loop has a dictionary of values associated with it.
        """
        # Startup and issue loop command
        self.startup()
        command = "LOOP " + str(loops) + "\n"
        self.msg(command)

        #collect data on per loop basis.
        daq = []
        for i in range(0, loops):
            data = self.receive_data()
            daq.append(data)

        return daq
    

    def print_data(self, data):
        """
            Prints contents of data collected from LOOP <loops> command.
            Loop: loop#
            Field : Value format. 
        """
        loop = 0
        for i in data:
            print("\n**************\nLoop {}:".format(loop))
            print("**************")
            for field in i:
                print("{} : {}".format(field, i[field]))
            loop+=1



    
