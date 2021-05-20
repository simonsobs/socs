# Tucker Elleflot
from socs.agent.prologix_interface import PrologixInterface


class PsuInterface(PrologixInterface):
    def __init__(self, ip_address, gpibAddr, verbose=False, **kwargs):
        self.verbose = verbose
        super().__init__(ip_address, gpibAddr, **kwargs)

    def enable(self, ch):
        '''
        Enables output for channel (1,2,3) but does not turn it on.
        Depending on state of power supply, it might need to be called
        before the output is set.
        '''
        self.set_chan(ch)
        self.write('OUTP:ENAB ON')

    def disable(self, ch):
        '''
        disabled output from a channel (1,2,3). once called, enable must be
        called to turn on the channel again
        '''
        self.write('OUTP:ENAB OFF')

    def set_chan(self, ch):
        self.write('inst:nsel ' + str(ch))

    def set_output(self, ch, out):
        '''
        set status of power supply channel
        ch - channel (1,2,3) to set status
        out - ON: True|1|'ON' OFF: False|0|'OFF'

        Calls enable to ensure a channel can be turned on. We might want to
        make them separate (and let us use disable as a safety feature) but
        for now I am thinking we just want to thing to turn on when we tell
        it to turn on.
        '''
        self.set_chan(ch)
        self.enable(ch)
        if isinstance(out, str):
            self.write('CHAN:OUTP '+out)
        elif out:
            self.write('CHAN:OUTP ON')
        else:
            self.write('CHAN:OUTP OFF')

    def get_output(self, ch):
        '''
        check if the output of a channel (1,2,3) is on (True) or off (False)
        '''
        self.set_chan(ch)
        self.write('CHAN:OUTP:STAT?')
        out = bool(float(self.read()))
        return out

    def set_volt(self, ch, volt):
        self.set_chan(ch)
        self.write('volt ' + str(volt))
        if self.verbose:
            voltage = self.get_volt(ch)
            print("CH " + str(ch) + " is set to " + str(voltage) + " V")

    def set_curr(self, ch, curr):
        self.set_chan(ch)
        self.write('curr ' + str(curr))
        if self.verbose:
            current = self.get_curr(ch)
            print("CH " + str(ch) + " is set to " + str(current) + " A")

    def get_volt(self, ch):
        self.set_chan(ch)
        self.write('MEAS:VOLT? CH' + str(ch))
        voltage = float(self.read())
        return voltage

    def get_curr(self, ch):
        self.set_chan(ch)
        self.write('MEAS:CURR? CH' + str(ch))
        current = float(self.read())
        return current
