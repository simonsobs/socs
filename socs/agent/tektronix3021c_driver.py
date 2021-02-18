"""Michael Randall
    mrandall@ucsd.edu"""

from socs.agent.prologix_interface import GpibInterface


class TektronixInterface(GpibInterface):
    def set_freq(self, freq):
        self.write('SOUR:FREQ {:.3f}\n'.format(freq))

    def set_amp(self, amp):
        self.write('SOUR:VOLT {:.3f}\n'.format(amp))

    def set_output(self, state):
        self.write('OUTP:STAT {:.0f}\n'.format(state))
