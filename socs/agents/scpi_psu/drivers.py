# Tucker Elleflot

import socket
import time

from socs.common.prologix_interface import PrologixInterface

# append new model strings as needed
ONE_CHANNEL_MODELS = ['2280S-60-3', '2280S-32-6']
THREE_CHANNEL_MODELS = ['2230G-30-1']


class ScpiPsuInterface:
    def __init__(self, ip_address, gpibAddr, port, **kwargs):
        self.ip_address = ip_address
        self.gpibAddr = gpibAddr
        self.port = port
        self.sock = None
        self.model = None
        self.numChannels = 0
        self.conn_socket()
        try:
            self.configure()
        except ValueError as err:
            raise ValueError(err)
        super().__init__(**kwargs)

    def conn_socket(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.connect((self.ip_address, self.port))
        self.sock.settimeout(5)

    def read(self):
        return self.sock.recv(128).decode().strip()

    def write(self, msg):
        message = msg + '\n'
        self.sock.sendall(message.encode())
        time.sleep(0.1)  # to prevent flooding the connection

    def identify(self):
        self.write('*idn?')
        return self.read()

    def read_model(self):
        idn_response = self.identify().split(',')[1]
        if (idn_response.startswith('MODEL')):
            return idn_response[6:]
        else:
            return idn_response

    def configure(self):
        self.model = self.read_model()
        if (self.model in ONE_CHANNEL_MODELS):
            self.numChannels = 1
        if (self.model in THREE_CHANNEL_MODELS):
            self.numChannels = 3
        if (self.numChannels == 0):
            raise ValueError('Model number not found in known device models', self.model)

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
            self.write('CHAN:OUTP ' + out)
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

    def set_curr(self, ch, curr):
        self.set_chan(ch)
        self.write('curr ' + str(curr))

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
            self.write('CHAN:OUTP ' + out)
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
