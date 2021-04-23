import aculib
import test_helpers as th
import time
import numpy as np
import pickle

import spem_model

import argparse
parser = argparse.ArgumentParser()
parser.add_argument('mode', default='passive', nargs='?')
args = parser.parse_args()


REFRAC_KEYS = [
    'Temperature',     # C
    'RelativeHumidity',# %
    'AirPressure',     # hPa
]
IGNORE_WRITEBACK = [] #'AN2', 'AW2']

class RefracHelper:
    """This works with simple parameter names (IA, etc) and values in
    degrees (rather than ACU internal mdeg).

    """
    DSET = 'DataSets.CmdWeatherStation'
    GLOBAL_EN = ('DataSets.CmdPointingCorrection',
                 'RF refraction correction on')
    
    def __init__(self, acu):
        self.acu = acu
            
    def global_enable(self, enable=None):
        if enable is None:
            return self.acu.Values(self.GLOBAL_EN[0])[self.GLOBAL_EN[1]]
        self.acu.Command(self.GLOBAL_EN[0], 'Set %s' % self.GLOBAL_EN[1],
                         int(bool(enable)))

    def clear(self, ignore=[]):
        vals = self.get(ignore=ignore)
        self.set({k: 0 for k in vals.keys()})
        return not any(self.get().values())

    def get(self, ignore=[]):
        raw = self.acu.Values(self.DSET)
        return {k: v for k, v in raw.items()
                if k not in ignore}

    def set(self, dict_arg=None, **kwargs):
        all_args = {}
        if dict_arg is not None:
            all_args.update(dict_arg)
        all_args.update(kwargs)
        for k, v in all_args.items():
            ret_val = self.acu.Command(self.DSET, 'Set %s' % k, '%f' % (v))
            if ret_val != 'OK, Command send.':
                raise RuntimeError('Failed to set parameter: %s' % k)


keep_going = True
def check_ok():
    if not keep_going:
        parser.exit("Exiting.")

def banner(title):
    print()
    print('*' * 60)
    print('   ' + title)
    print('*' * 60)
    

acu = aculib.AcuControl()

banner('Check Datasets Present')

for dset in [
        'DataSets.StatusSATPDetailed8100',
        'DataSets.StatusPointingCorrection',
        'DataSets.CmdWeatherStation',
        ]:
    try:
        v1 = acu.Values(dset)
        print('  Retrieved %-40s - %i keys' % (dset, len(v1)))
    except aculib.http.HttpError as e:
        print('  ! Failed to retrieve %s' % dset)
        keep_going = False

check_ok()

banner('Check SPEM Against Schema')

refh = RefracHelper(acu)
excess_keys = refh.get().keys()
missing_keys = [k for k in REFRAC_KEYS]
print('  Read %i keys (expecting %i)' % (len(excess_keys), len(missing_keys)))

both = set(missing_keys).intersection(excess_keys)
missing_keys = list(set(missing_keys).difference(both))
excess_keys = list(set(excess_keys).difference(both))
if len(missing_keys):
    print('  Expected but did not find these keys:')
    print('    ' + ', '.join(missing_keys))
    keep_going = False
if len(excess_keys):
    print('  Found but did not expect these keys:')
    print('    ' + ', '.join(excess_keys))
    keep_going = False
check_ok()


banner('Check write-back all Refrac parameters')

if not th.check_remote(acu):
    print('ACU is not in remote mode!')
    keep_going = False
check_ok()

for k, v in refh.get().items():
    try:
        refh.set({k: v})
    except:
        print('  Failed to write %s!' % k)
        if k not in IGNORE_WRITEBACK:
            keep_going = False
        continue

print('  Write-back test complete.')
check_ok()

banner('Confirm ACU in Stop')

if acu.mode() != 'Stop':
    print('  Any further testing requires ACU to be in stop.')
    keep_going = False
else:
    print('  ACU is in stop.')
check_ok()


banner('Check Refrac responsiveness')
model0 = {'Temperature': 15.0,
          'RelativeHumidity': 10.0,
          'AirPressure': 500.0}
dmodel = {'Temperature': 25.0,
          'RelativeHumidity': 60.0,
          'AirPressure': 600.0}

refh.global_enable(True)
refh.set(model0)
pos0 = th.get_positions(acu)
print('Current position:', pos0)

for k, v in dmodel.items():
    m = dict(model0)
    m[k] = v
    refh.set(m)
    pos1 = th.get_positions(acu)
    print('    Set %-20s = %8.3f ... ' % (k, v) + ' delta pos in arcsecs: ', (pos1-pos0) * 3600.)

refh.global_enable(False)
pos1 = th.get_positions(acu)
print('    And with model disabled ...              delta pos in arcsecs: ', (pos1-pos0) * 3600.)


if args.mode == 'survey':
    banner('Make a survey of corrections over many pointings.')

    model = {'Temperature': 15.0,
             'RelativeHumidity': 10.0,
             'AirPressure': 500.0}
    refh.global_enable(False)
    refh.set(model)

    # Move through various elevations, apply the model at each and
    # measure the offsets.
    data = []  # [cmd, meas0, meas1]
    az = th.get_positions(acu)[0]  # use current pos.
    for el in [40, 50, 60]:
        print('Moving to az=%.2f el=%.2f' % (az, el))
        acu.go_to(az, el)
        while not th.check_positions(acu, az, el):
            time.sleep(.5)
        print('  setting stop mode.')
        acu.stop()
        time.sleep(.2)
        pos0 = th.get_positions(acu)
        refh.global_enable(True)
        time.sleep(.2)
        pos1 = th.get_positions(acu)
        refh.global_enable(False)
        print('  delta pos is ', pos1-pos0)
        data.append([np.array([az, el]), pos0, pos1])
    data = np.array(data)
    print(data.shape)

    # Write out model and params.
    filename = 'refrac_survey_%i.pik' % int(time.time())
    with open(filename, 'wb') as fout:
        pickle.dump({'model': model,
                     'data': data}, fout)
    
