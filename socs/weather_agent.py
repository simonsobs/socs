from serial import Serial
import time
import struct
import os
from datetime import datetime
import array as arr

BUFF_SIZE = 1024

class WeatherAgent:
    """
        Allows communication to Vantage Pro 2 Weather Monitor Module.
        Contains commands to be issued and member variables that store collected data.
    """

    def __init__(self, baud=19200, timeout=1):
        """
            Establish serial connection and initialize member variables
        """

        #takes first occurence of ttyUSB location, and assumes this is the correct location of the weather module
        path = '/dev'
        for fname in os.listdir(path):
            if fname[0:6] == 'ttyUSB':
                usb = fname
        path += "/" + usb        
        self.com = Serial(port = path, baudrate=baud, timeout=timeout)

        #wakeup vantage pro 2 module
        self.com.close()
        self.com.open()
        for i in range(0, 3):
            self.com.write(b"\n")
            response = self.com.readlines()
            if response:
                break
            time.sleep(0.1)
            if i == 2:
                raise TimeoutError("Timeout error")
        
        #loop_data is (will be) a list of dictionaries. 
        self.loop_data = [  ]

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


    def calc_crc(self, data):
        """
            Calculates CRC
        """
        crc = 0
        for i in data:
            crc = self.crc_table [(crc >> 8) ^ i] ^ (crc << 8)
        return crc


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
        self.com.write(b'RXTEST\n')
        time.sleep(0.5)

        #reads response from console
        self.com.read(6)


    def msg(self, msg):
        """
            Send general command or query to module.
            If command received and acknowledged, continue
        """
        self.com.write(bytes(msg, 'ascii'))
        time.sleep(0.1)
        ack = self.com.read(1)
        if not ack:
            raise TimeoutError("Command not acknowledged")


    def interrupt_daq(self):
        """
            Interrupts loop command...if sent before loop command finishes
        """
        self.com.write(b'\n')
        for i in range(0, 3):
            response = self.com.read(99)
            if response == b'\n\r':
                return True
            time.sleep(0.1)
            if i == 2:
                return False

    
    def receive_data(self, loops):
        """
            Reads loop data from console and writes to self.loop_data[{}]
        """
        info = b''
        for i in range(0, loops):
            info = self.com.read(99)  
            time.sleep(0.5)
            if not info:
                raise TimeoutError("Timeout error")
            self.loop_data.append({})    

            # self.loop_data[i]{field} = value
            self.loop_data[i].update({'LOO'                         : struct.unpack('3c', info[:3])})
            self.loop_data[i].update({'bar_trend'                   : struct.unpack('1b', info[3:4])[0]})
            self.loop_data[i].update({'packet_type'                 : struct.unpack('1b', info[4:5])[0]})
            self.loop_data[i].update({'next_record'                 : struct.unpack('1h', info[5:7])[0]}) 
            self.loop_data[i].update({'barometer'                   : struct.unpack('1h', info[7:9])[0] / 1000.0})
            self.loop_data[i].update({'in_temp'                     : struct.unpack('1h', info[9:11])[0] / 10.0})
            self.loop_data[i].update({'in_hum'                      : struct.unpack('1b', info[11:12])[0]})
            self.loop_data[i].update({'out_temp'                    : struct.unpack('1h', info[12:14])[0] / 10.0})
            self.loop_data[i].update({'wind_speed'                  : struct.unpack('1B', info[14:15])[0]})
            self.loop_data[i].update({'avg_wind_speed'              : struct.unpack('1B', info[15:16])[0]})
            self.loop_data[i].update({'wind_dir'                    : struct.unpack('1H', info[16:18])[0]})
            self.loop_data[i].update({'extra_temps'                 : struct.unpack('7b', info[18:25])})
            self.loop_data[i].update({'soil_temps'                  : struct.unpack('4b', info[25:29])})
            self.loop_data[i].update({'leaf_temps'                  : struct.unpack('4b', info[29:33])})
            self.loop_data[i].update({'out_hum'                     : struct.unpack('1b', info[33:34])[0]})
            self.loop_data[i].update({'extra_hums'                  : struct.unpack('7b', info[34:41])})
            self.loop_data[i].update({'rain_rate'                   : struct.unpack('1h', info[41:43])[0]})
            self.loop_data[i].update({'uv'                          : struct.unpack('1b', info[43:44])[0]})
            self.loop_data[i].update({'solar_rad'                   : struct.unpack('1h', info[44:46])[0]})
            self.loop_data[i].update({'storm_rain'                  : struct.unpack('1h', info[46:48])[0]})
            self.loop_data[i].update({'storm_start'                 : struct.unpack('1h', info[48:50])[0]})
            self.loop_data[i].update({'day_rain'                    : struct.unpack('1h', info[50:52])[0]})
            self.loop_data[i].update({'month_rain'                  : struct.unpack('1h', info[52:54])[0]})
            self.loop_data[i].update({'year_rain'                   : struct.unpack('1h', info[54:56])[0]})
            self.loop_data[i].update({'day_ET'                      : struct.unpack('1h', info[56:58])[0]})
            self.loop_data[i].update({'month_ET'                    : struct.unpack('1h', info[58:60])[0]})
            self.loop_data[i].update({'year_ET'                     : struct.unpack('1h', info[60:62])[0]})
            self.loop_data[i].update({'soil_moistures'              : struct.unpack('4b', info[62:66])})
            self.loop_data[i].update({'leaf_wetnesses'              : struct.unpack('4b', info[66:70])})
            self.loop_data[i].update({'in_alarms'                   : struct.unpack('1b', info[70:71])[0]})
            self.loop_data[i].update({'rain_alarm'                  : struct.unpack('1b', info[71:72])[0]})
            self.loop_data[i].update({'out_alarms'                  : struct.unpack('2b', info[72:74])})
            self.loop_data[i].update({'extra_temp/hum_alarms'       : struct.unpack('8b', info[74:82])})
            self.loop_data[i].update({'soil_leaf_alarms'            : struct.unpack('4b', info[82:86])})
            self.loop_data[i].update({'transmitter_battery_status'  : struct.unpack('1b', info[86:87])[0]})
            self.loop_data[i].update({'console_battery_voltage'     : struct.unpack('1h', info[87:89])[0]})
            self.loop_data[i].update({'forecast_icons'              : struct.unpack('1b', info[89:90])[0]})
            self.loop_data[i].update({'forecast_rule_num'           : struct.unpack('1b', info[90:91])[0]})
            self.loop_data[i].update({'time_sunrise'                : struct.unpack('1h', info[91:93])[0]})
            self.loop_data[i].update({'time_sunset'                 : struct.unpack('1h', info[93:95])[0]})
        

    def weather_daq(self, loops):
        """
            Issues "LOOP <loops>" command to weather station, and unpacks/stores
            the data to self.loop_data[{}]. Each loop has a dictionary of values associated with it.
        """
        command = "LOOP " + str(loops) + "\n"
        self.msg(command)
        self.receive_data(loops)
        

    def get_data(self):
        """
        Returns data gathered from the loop command
        """
        return self.loop_data
    

    def print_data(self):
        """
            Prints contents of data collected from LOOP <loops> command.
            Loop: loop#
            Field : Value format. 
        """
        loop = 0
        for i in self.loop_data:
            print("\n**************\nLoop {}:".format(loop))
            print("**************")
            for field in i:
                print("{} : {}".format(field, i[field]))
            loop+=1


    # def set_time(self):
    #     """
    #         Attempt at setting time on vantage pro 2 console. Fails CRC: it indexes out of the crc_table array....
    #     """
    #     self.com.write(b'SETTIME\n')
    #     time.sleep(0.1)
    #     ack = self.com.read(1)
    #     now = datetime.now()
    #     byte_date = arr.array('H', [now.second, now.minute, now.hour, now.day, now.month, now.year - 1900])
    #     crc = self.calc_crc(byte_date)
    #     for i in  byte_date:
    #         self.com.write(i)
    #     self.com.write(crc)

        # ----------------------------------------
        # checking if time is correctly written
        # ----------------------------------------
        # ack = self.com.read(1)
        # self.com.write(b'GETTIME\n')
        # ack = self.com.read(1)
        # time1 = self.com.read(8)
        # print(time1)

    
