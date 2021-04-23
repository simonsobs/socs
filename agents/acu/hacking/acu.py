import requests
import json
from collections import OrderedDict
import struct

class AcuInterface:
    base_url = 'http://172.16.5.95:8100/'
    #base_url = 'http://172.16.5.95:8110/'  #readonly!
    
    def params_values(self, ident, fmt='json'):
        return {'identifier': ident,
                'format': fmt}

    def request_values(self, ident, fmt='json'):
        return requests.get('%s%s' % (self.base_url, 'Values'), 
                            params=self.params_values(ident, fmt=fmt))

    def request_docs(self, ident, fmt='html'):
        return requests.get('%s%s' % (self.base_url, 'Documentation'),
                            params=self.params_values(ident, fmt=fmt))

    def request_command(self, ident, cmd, val=None):
        # e.g. (Antenna.SkyAxes,
        #       SetAzElMode,
        #       Preset)
        params = {
            'identifier': ident,
            'command': cmd,
        }
        if val is not None:
            params['parameter'] = val
        return requests.get('%s%s' % (self.base_url, 'Command'),
                            params=params)

    def request_write(self, identifier, data):
        # This is used to post binary data to a particular data set.
        # User takes responsibility for packing data properly...
        return requests.post('%s%s' % (self.base_url, 'Write'),
                             params={'identifier': identifier},
                             data=data)

    def request_upload(self, text, filename='Test'):
        return requests.post('%s%s' % (self.base_url, 'UploadPtStack'),
                             params={'filename': filename,
                                     'Type': 'File'},
                             data=text)

    def request_upload2(self, text):
        # This mimics the UploadPtStack?type=Form submission as closely as possible.
        return requests.post('%s%s' % (self.base_url, 'UploadPtStack'),
                             params={'filename': 'UpoadedFromBrowser',
                                     'type': 'FileMultipart'},
                             files={'upload': ('acu.txt', text, 'text/plain')})
        return r

class Pointing:
    def __init__(self, acu=None):
        if acu is None:
            acu = AcuInterface()
        self.acu = acu
    def stop(self):
        t = self.acu.request_command('DataSets.CmdModeTransfer', 'Stop')
    def go(self, az=None, el=None):
        if az is not None or el is not None:
            self(az,el)
        t = self.acu.request_command('DataSets.CmdModeTransfer', 'SetAzElMode', 'Preset')
    def status(self):
        t1 = ordered_json(self.acu.request_values('Antenna.SkyAxes.Azimuth').text)
        t2 = ordered_json(self.acu.request_values('Antenna.SkyAxes.Elevation').text)
        return {'az': t1, 'el': t2}
    def __call__(self, az=None, el=None):
        stat = self.status()
        cmd, par = [], []
        if az is not None:
            cmd.append('Azimuth')
            par.append('%.4f' % az)
        if el is not None:
            cmd.append('Elevation')
            par.append('%.4f' % el)
        if len(cmd):
            ## This works, but the docs (2.0) do not say so.
            cmd = 'Set ' + ' '.join(cmd)
            par = '|'.join(par)
            t = self.acu.request_command('DataSets.CmdAzElPositionTransfer', cmd, par)
            ## The binary is cool, but only if you're writin az and el
            ## at the same time.
            #packed = struct.pack('dd', az, el)
            #t = self.acu.request_write('DataSets.CmdAzElPositionTransfer', packed)
            print(t)
        return '[ACU az:{az[Mode]}:{az[Position]:.4f} el:{el[Mode]}:{el[Position]:.4f}]'.format(**self.status())

class PositionBroadcast:
    base_url = 'http://172.16.5.95:8080/'
    def enable(self, enable=True):
        params = {'Module': 'Services.PositionBroadcast',
                  'Chapter': '3',}
        data = {'Command': {True: 'Enable', False: 'Disable'}[enable]}
        return requests.post('%s/' % (self.base_url,),
                             data=data, params=params)
    def destination(self, ip_address='172.16.5.10', port=10000):
        params = {'Module': 'Services.PositionBroadcast',
                  'Chapter': '1',}
        data = {'name': 'Destination',
                'value': ip_address}
        r1 = requests.post('%s/' % (self.base_url,),
                           data=data, params=params)
        data = {'name': 'Port',
                'value': '%i' % port}
        r2 = requests.post('%s/' % (self.base_url,),
                           data=data, params=params)

def ordered_json(text):
    return json.loads(text, object_pairs_hook=OrderedDict)


if __name__ == '__main__':
    acu = AcuInterface()
    print('acu is a AcuInterface')
    p = Pointing(acu)
    print('p is a Pointing.')
    pb = PositionBroadcast()
    print('pb is a PositionBroadcast.')
    print(p())
    #r = pb.enable(False)
