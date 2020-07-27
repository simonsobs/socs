# Tucker Elleflot
from socs.agent import prologixInterface


class psuInterface:

    def __init__(self, ip_address, gpibAddr, verbose=True):
        self.pro = prologixInterface.prologixInterface(ip=ip_address)

        self.gpibAddr = gpibAddr
        self.verbose = verbose

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

    def enable(self, ch):
        '''
        Enables output for channel (1,2,3) but does not turn it on. 
        Depending on state of power supply, it might need to be called
        before the output is set. 
        '''
        self.setChan(ch)
        self.write('OUTP:ENAB ON')
        
    def disable(self, ch):
        '''
        disabled output from a channel (1,2,3). once called, enable must be 
        called to turn on the channel again
        '''
        self.write('OUTP:ENAB OFF')

    def setChan(self, ch):
        self.write('inst:nsel ' + str(ch))

    def setOutput(self, ch, out):
        '''
        set status of power supply channel
        ch - channel (1,2,3) to set status
        out - ON: True|1|'ON' OFF: False|0|'OFF'

        Calls enable to ensure a channel can be turned on. We might want to 
        make them separate (and let us use disable as a safety feature) but
        for now I am thinking we just want to thing to turn on when we tell
        it to turn on.
        '''
        self.setChan(ch)
        self.enable(ch)
        if type(out)==str:
            self.write('CHAN:OUTP '+out)
        elif out:
            self.write('CHAN:OUTP ON')
        else:
            self.write('CHAN:OUTP OFF')

    def getOutput(self, ch):
        '''
        check if the output of a channel (1,2,3) is on (True) or off (False)
        '''
        self.setChan(ch)
        self.write('CHAN:OUTP:STAT?')
        out = bool(float(self.read()))
        return out

    def setVolt(self, ch, volt):
        self.setChan(ch)
        self.write('volt ' + str(volt))
        #if self.verbose:
        #    voltage = self.getVolt(ch)
            #print "CH " + str(ch) + " is set to " + str(voltage) " V"

    def setCurr(self, ch, curr):
        self.setChan(ch)
        self.write('curr ' + str(curr))
        #if self.verbose:
        #    current = self.getCurr(ch)
            #print "CH " + str(ch) + " is set to " + str(current) " A"

    def getVolt(self, ch):
        self.setChan(ch)
        self.write('MEAS:VOLT? CH' + str(ch))
        voltage = float(self.read())
        return voltage

    def getCurr(self, ch):
        self.setChan(ch)
        self.write('MEAS:CURR? CH' + str(ch))
        current = float(self.read())
        return current
