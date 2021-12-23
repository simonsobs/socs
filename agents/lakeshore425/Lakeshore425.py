import serial
import time

operational_status_key = [ 
    'No probe',
    'Field overload',
    'New field reading',
    'Alarm',
    'Invalid probe',
    'None',
    'Calibration error'
    'Zero probe done'
]

class LakeShore425():
    def __init__(self, COM):
        self.port = serial.Serial(
            COM,                         
            baudrate=57600,                        
            bytesize=serial.SEVENBITS,                        
            parity=serial.PARITY_ODD,                        
            stopbits=serial.STOPBITS_ONE,
            timeout=5,
            xonxoff=False,
            rtscts=False,
            write_timeout=None,
            dsrdtr=False,
            inter_byte_timeout=None
        )
    def close(self):
        self.port.close()
    def read(self):
        return self.port.readline().strip().decode('utf-8')
    def wait(self):
        time.sleep(.1)
    def IDN(self):
        self.port.write(b"*IDN?\r\n")
        return self.read()
    def OPST(self):
        self.port.write(b"OPST?\r\n")
        val = int(self.read())
        out = 'Operational Status: '
        for i in range(8):
          if (val>>i& 1):
            out += operational_status_key[i]   
            out += ', '
        return out 
    def getField(self):
        tmp = "RDGFIELD?\r\n"
        self.port.write(tmp.encode('utf-8'))
        return float(self.read())
    def ZeroCalibration(self):
        self.port.write(b"ZCLEAR\r\n")
        self.wait()
        self.port.write(b"ZPROBE\r\n")
    def anycommand(self, command):
        tmp = command + "\r\n"
        self.port.write(tmp.encode('utf-8'))
        self.wait()
        print(self.read())
