from acu import *

def translate(input):
    output = OrderedDict()
    for k in input.keys():
        if k == 'Azimuth Mode':
            output[k] = {
                }

acu = AcuInterface()

# Monitor position?
mr='Datasets.StatusGeneral8100'
# This doesn't seem to have the "OnPosition" variable, which is how to
# tell that the motion is completed (or that ACU thinks it has).

import time
while True:
    t = acu.request_values(mr).json()
    print('az[{t[Azimuth Mode]}]={t[Azimuth current position]:8.4f} '
          'el[{t[Elevation Mode]}]={t[Elevation current position]:8.4f} '
          .format(t=t),end='')
    print('  and:  [{t[OnPosition]}]'
          .format(t=acu.request_values('Antenna.SkyAxes.Azimuth').json()))
    #print(time.time())
    
