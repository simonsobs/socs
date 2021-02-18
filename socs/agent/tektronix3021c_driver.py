"""Michael Randall
    mrandall@ucsd.edu"""

from socs.agent.prologixInterface import GpibInterface


class tektronixInterface(GpibInterface):
    def setFreq(self, freq):
        self.write('SOUR:FREQ {:.3f}\n'.format(freq))

    def setAmp(self, amp):
        self.write('SOUR:VOLT {:.3f}\n'.format(amp))

    def setOutput(self, state):
        self.write('OUTP:STAT {:.0f}\n'.format(state))
