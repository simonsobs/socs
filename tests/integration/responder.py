import serial
import time

port2 = serial.Serial(
    './port2',
    baudrate=57600,
    #bytesize=serial.SEVENBITS,
    #parity=serial.PARITY_ODD,
    #stopbits=serial.STOPBITS_ONE,
    #timeout=5,
    #xonxoff=False,
    #rtscts=False,
    #write_timeout=None,
    #dsrdtr=False,
    #inter_byte_timeout=None
)

responses = {'*IDN?': 'LSCI,MODEL425,4250022,1.0',
             'RDGFIELD?': '+1.0E-01'}

while True:
    msg = port2.readline().strip().decode('utf-8')
    print(f"{msg=}")
    try:
        print('response:', responses[msg])
        port2.write((responses[msg] + '\r\n').encode('utf-8'))
    except Exception as e:
        print(f"encountered error {e}")
    time.sleep(0.1)
