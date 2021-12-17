import sys
import string
import gclib
import time

class DCM_func:
    def __init__(self) -> None:
        self.controller = gclib.py()
        try:
            self.controller.GOpen('192.168.1.100')
            print('Here is a controller: ', self.controller.GVersion())
            self.cm = self.controller.GCommand
            pass
        except:
            print('Failed to connect a controller.\n')
            pass
        pass

    def read_status(self):
        print('--- Here is digital I/O flags. ---\n')
        print('digital_in1 = {:6s}, digital_out1 = {:6s}'.format(self.cm('MG @IN[1]'), self.cm('MG @OUT[1]')))
        print('digital_in2 = {:6s}, digital_out2 = {:6s}'.format(self.cm('MG @IN[2]'), self.cm('MG @OUT[2]')))
        print('digital_in3 = {:6s}, digital_out3 = {:6s}'.format(self.cm('MG @IN[3]'), self.cm('MG @OUT[3]')))
        print('digital_in4 = {:6s}, digital_out4 = {:6s}'.format(self.cm('MG @IN[4]'), self.cm('MG @OUT[4]')))
        print('digital_in5 = {:6s}, digital_out5 = {:6s}'.format(self.cm('MG @IN[5]'), self.cm('MG @OUT[5]')))
        print('digital_in6 = {:6s}, digital_out6 = {:6s}'.format(self.cm('MG @IN[6]'), self.cm('MG @OUT[6]')))
        print('digital_in7 = {:6s}, digital_out7 = {:6s}'.format(self.cm('MG @IN[7]'), self.cm('MG @OUT[7]')))
        print('digital_in8 = {:6s}, digital_out8 = {:6s}'.format(self.cm('MG @IN[8]'), self.cm('MG @OUT[8]')))

        print('--- Here is motor conditions. ---\n')
        print('Motor type: MTA = {:6s}, MTB = {:6s}'.format(self.cm('MTA=?'), self.cm('MTB=?')))
        print('Master of the axis: GAA = {:6s}, GAB = {:6s}'.format(self.cm('GAA=?'), self.cm('GAB=?')))
        print('Ampair Gain: AGA = {:6s}, AGB = {:6s}'.format(self.cm('AGA=?'), self.cm('AGB=?')))
        print('Gear Ratio: GRA = {:6s}, GRB = {:6s}'.format(self.cm('GRA=?'), self.cm('GRB=?')))
        print('micro-stepping: YAA = {:6s}, YAB = {:6s}'.format(self.cm('YAA=?'), self.cm('YAB=?')))
        print('motor resolution: YBA = {:6s}, YBB = {:6s}'.format(self.cm('YBA=?'), self.cm('YBB=?')))
        print(' [ encoder resolution: YCA = {:6s}, YCB = {:6s} ] '.format(self.cm('YCA=?'), self.cm('YCB=?')))
        print('Smoothing: KSA = {:6s}, KSB = {:6s}'.format(self.cm('KSA=?'), self.cm('KSB=?')))
        print('Speed: SPA = {:6s}, SPB = {:6s}'.format(self.cm('SPA=?'), self.cm('SPB=?')))
        print('Position Relative: PRA = {:6s}, PRB = {:6s}'.format(self.cm('PRA=?'), self.cm('PRB=?')))
        print('----------------------------------')
        pass

    def set_motors(self, prn=10000):
        print('--- Motor Initializing. ---\n')
        self.cm('ST')
        self.cm('MO')
        self.cm('MT 2, 2') # set motor type/ 2:stepping motor
        self.cm('AG 3, 3') # set ampair gain 3 A
        self.cm('GA= N, N') # set master axis of the A and B axis
        self.cm('YA= 8, 8') # set microstepping
        self.cm('YB= 200, 200') # set motor resolution
        self.cm('KS= 16, 16') # set pulse smoothing
        self.cm('SP= 100, 100')
        self.cm('PR= 100, 100')
        self.cm('SPN= 2000') # set speed of the master axis, N
        self.cm('SH ABN') # activating all the axis
        print('----------- Done. ----------\n')
        self.read_status
        print('Next: set moving distance w/ set_distance')
        pass

    def set_distance(self, prn=10000):
        print('--- Setting counter size. ---\n')
        self.cm('PRN= '+str(prn)) # set position relative of the master, N
        print('--- increment: {} ---\n'.format(str(prn)))
        print('Next: you have motors move w/ get_rotation w/ arg "f"(forword) or "b"(backword)')
        pass

    def get_rotate(self, direction):
        if direction == 'f':
            print('--- Move Forward. ---\n')
            self.cm('GR= 1, -1') # set gear ratio
            time.sleep(0.1)
            self.cm('BG N')
            pass
        elif direction == 'b':
            print('--- Move Backward. ---\n')
            self.cm('GR= -1, 1') # set gear ratio
            time.sleep(0.1)
            self.cm('BG N')
            pass
        print('----- Stopped. -----')
        pass

    def stopit(self):
        self.cm('ST') # stop motor rotation
        time.sleep(0.1)
        self.cm('MO') # deactivationg motors
        print('--- Motors disactivating. ---\n')
        print('Please set motors again, set_motors, or delete this instance, close_motors')
        pass

    def close_motors(self):
        self.cm('MO') # deactivationg motors
        time.sleep(0.2)
        self.controller.GClose()
        print('Controller instance has deleted.')
        pass

if __name__=='__main__':
    print('This is test class for motor control. Please import DCM_func.')
    pass
