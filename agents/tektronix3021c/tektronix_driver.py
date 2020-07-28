"""Michael Randall
    mrandall@ucsd.edu"""

import prologixInterface

class tektronixInterface:
    
    def __init__(self, ip_address, gpibAddr, verbose=True):
        self.pro = prologixInterface.prologixInterface(ip=ip_address)
        
        self.verbose = verbose
        self.gpibAddr = gpibAddr

    
    def connGpib(self):
        self.pro.write('++addr ' + str(self.gpibAddr))

        
    def write(self, msg):
        self.connGpib()
        self.pro.write(msg)


    def read(self):
        return self.pro.read()


    def identify(self):
        self.write('*idn?')
        return self.read()
    
    
    def setFreq(self, freq):
        #gpib_connect(awg_gpib_addr)
        self.write('SOUR:FREQ {:.3f}\n'.format(freq))
        
        """
        if self.verbose:
            self.p.send('SOUR:FREQ?\n')
            freq_set = float(self.p.recv(128).rstrip())
    
            print('freq: {:.3e} Hz').format(freq_set)
        """
    
    def setAmp(self, amp):
        #self.gpib_connect(self.awg_gpib_address)
        self.write('SOUR:VOLT {:.3f}\n'.format(amp))
        
        """
        if self.verbose:
            self.p.send('SOUR:VOLT?\n')
            amp_set = float(self.p.recv(128).rstrip())
    
            print('set amp: {:.3e} V'.format(amp_set))
        """
    
    def setOutput(self, state):
        #self.gpib_connect(self.awg_gpib_address)
        self.write('OUTP:STAT {:.0f}\n'.format(state))
    
        """
        if self.verbose:
            self.p.send('OUTP:STAT?\n')
            state_set = float(self.p.recv(128).rstrip())
    
            print('output state: {:.0f}'.format(state_set))
        """





