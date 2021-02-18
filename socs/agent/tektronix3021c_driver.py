"""Michael Randall
    mrandall@ucsd.edu"""

from socs.agent.prologix_interface import GPIBInterface


class tektronixInterface(GPIBInterface):
    def setFreq(self, freq):
        self.write('SOUR:FREQ {:.3f}\n'.format(freq))

    def setAmp(self, amp):
        self.write('SOUR:VOLT {:.3f}\n'.format(amp))

    def setOutput(self, state):
        self.write('OUTP:STAT {:.0f}\n'.format(state))
