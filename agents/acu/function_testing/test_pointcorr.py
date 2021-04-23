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


SPEM_KEYS = [
    'IA', 'IE',
    'TF', 'TFS',
    'AN', 'AW',
    'AN2', 'AW2',
    'NPAE',
    'CA',
    'AES', 'AEC', 'AES2', 'AEC2',
    #'EES' ... no elevation ellipticity.
]
IGNORE_WRITEBACK = ['AN2', 'AW2']

class SpemHelper:
    """This works with simple parameter names (IA, etc) and values in
    degrees (rather than ACU internal mdeg).

    """
    DSET = 'DataSets.CmdSPEMParameter'
    GLOBAL_EN = ('DataSets.CmdPointingCorrection',
                 'Systematic error model (SPEM) on')
    
    MDEG = 0.001

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
        # Strip "Parameter " from start of each key.
        raw = self.acu.Values(self.DSET)
        cleaned = {k.split()[-1]: float(v) * self.MDEG for k, v in raw.items()}
        return {k: v for k, v in cleaned.items()
                if k not in ignore}

    def set(self, dict_arg=None, **kwargs):
        all_args = {}
        if dict_arg is not None:
            all_args.update(dict_arg)
        all_args.update(kwargs)
        for k, v in all_args.items():
            ret_val = self.acu.Command(self.DSET, 'Set Spem_%s' % k, '%f' % (v / self.MDEG))
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
        'DataSets.CmdSPEMParameter',
        ]:
    try:
        v1 = acu.Values(dset)
        print('  Retrieved %-40s - %i keys' % (dset, len(v1)))
    except aculib.http.HttpError as e:
        print('  ! Failed to retrieve %s' % dset)
        keep_going = False

check_ok()

banner('Check SPEM Against Schema')

spemh = SpemHelper(acu)
excess_keys = spemh.get().keys()
missing_keys = [k for k in SPEM_KEYS]
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


banner('Check write-back all SPEM parameters')

if not th.check_remote(acu):
    print('ACU is not in remote mode!')
    keep_going = False
check_ok()

for k, v in spemh.get().items():
    try:
        spemh.set({k: v})
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


banner('Check SPEM responsiveness')

pos0 = th.get_positions(acu)
print('Current position:', pos0)

# Test basic offsets.
for param in ['IA', 'IE']:
    val = 0.1 # deg
    print('Set %s=%f deg' % (param, val))
    spemh.set({param: val})
    print('     new position:', th.get_positions(acu))
    spemh.set({param: 0})


banner('Check global enable')

spemh.clear(ignore=IGNORE_WRITEBACK)
pos0 = th.get_positions(acu)
print('  Starting position is az=%8.4f, el=%8.4f' % tuple(pos0))

spemh.set({'IA': 0.3, 'IE': -0.4})

pos1 = th.get_positions(acu)
print('  After SPEM model     az=%8.4f, el=%8.4f' % tuple(pos1))

spemh.global_enable(False)
pos2 = th.get_positions(acu)
print('  After SPEM disable   az=%8.4f, el=%8.4f' % tuple(pos2))

spemh.global_enable(True)
pos3 = th.get_positions(acu)
print('  After SPEM enable    az=%8.4f, el=%8.4f' % tuple(pos3))

spemh.clear(ignore=IGNORE_WRITEBACK)
pos4 = th.get_positions(acu)
print('  After SPEM clear     az=%8.4f, el=%8.4f' % tuple(pos4))

    
if args.mode == 'singles':
    # A good mode for debugging individual parameter equations.
    banner('Test response to each parameter.')

    spemh.clear(ignore=IGNORE_WRITEBACK)
    model0 = spemh.get()
    pos0 = th.get_positions(acu)
    print('  Starting position is az=%8.4f, el=%8.4f' % tuple(pos0))
    for k in SPEM_KEYS:
        if k in IGNORE_WRITEBACK:
            continue
        D = 0.4
        spemh.set({k: D})
        model = dict(model0)
        model[k] = D
        time.sleep(.2)
        pos1 = th.get_positions(acu)
        spemh.set({k: 0})
        expected = spem_model.delta(pos0, model)
        print('    For %-4s = %4.2f only:  ' % (k, D) +
              'expect [%+7.4f,%+7.4f] ' % tuple(expected) +
              'and measure [%+7.4f,%+7.4f]' % tuple(pos1 - pos0),
              end='')
        if (abs(expected - (pos1-pos0)).sum() > 1e-4):
            print(' ! Mismatch.')
        else:
            print(' * ok')


if args.mode == 'survey':
    # A good mode for checking that model makes sense across the sky.

    banner('Make a survey of corrections over many pointings.')

    model = {'IA':  .1,
             'IE':  .2,
             'TF':  .3,
             #'TFC': .4,
             'TFS': .5,
             'AN': -.1,
             'AW': -.2,
             }

    # Move through various positions, apply the model at each and
    # measure the offsets.
    data = []  # [cmd, meas0, meas1]
    for el in [40, 50, 60]:
        for az in [160, 180, 200]:
            print('Moving to az=%.2f el=%.2f' % (az, el))
            acu.go_to(az, el)
            spemh.clear(ignore=IGNORE_WRITEBACK)
            while not th.check_positions(acu, az, el):
                time.sleep(.5)
            print('  setting stop mode.')
            acu.stop()
            time.sleep(.2)
            pos0 = th.get_positions(acu)
            spemh.set(model)
            time.sleep(.2)
            pos1 = th.get_positions(acu)
            print('  delta pos is ', pos1-pos0)
            data.append([np.array([az, el]), pos0, pos1])
    data = np.array(data)
    print(data.shape)

    # Write out model and params.
    filename = 'spem_survey_%i.pik' % int(time.time())
    with open(filename, 'wb') as fout:
        pickle.dump({'model': model,
                     'data': data}, fout)
    
