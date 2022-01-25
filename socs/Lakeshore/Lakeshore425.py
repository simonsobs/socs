import serial
import time

operational_status_key = [ 
    'No probe',
    'Field overload',
    'New field reading',
    'Alarm',
    'Invalid probe',
    'None',
    'Calibration error',
    'Zero probe done'
]
class LakeShore425:
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

    def command(self, command):
        tmp = command + "\r\n"
        self.port.write(tmp.encode('utf-8'))
        time.sleep(.1)

    def query(self, command):
        self.command(command)
        return self.port.readline().strip().decode('utf-8')

    # Commands/Queries
    def get_id(self):
        return self.query("*IDN?")

    def get_op_status(self):
        val = int(self.query("OPST?"))
        out = 'Operational Status: '
        for i in range(8):
            if (val >> i & 1):
                out += operational_status_key[i]
                out += ', '
        return out

    def get_field(self):
        return float(self.query("RDGFIELD?"))

    def set_zero(self):
        self.command("ZCLEAR")
        self.command("ZPROBE")
