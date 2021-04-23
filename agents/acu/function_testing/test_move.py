import aculib
import test_helpers as th
import time
import numpy as np

acu = aculib.AcuControl()
HOME = 180, 60

if th.check_positions(acu, *HOME):
    print('ACU is already home.')
else:
    print('Sending home for start of test.')
    acu.go_to(*HOME)
    while not th.check_positions(acu, *HOME):
        print(' ... now at (%.3f,%.3f)' % th.get_positions(acu))
        time.sleep(1)

print('Measuring az speed.')
if th.check_positions(acu, *HOME):
    target = HOME[0] + 60, HOME[1]
else:
    target = HOME

acu.go_to(*target)
xt = []
while not th.check_positions(acu, *target):
    x = th.get_positions(acu)[0]
    t = time.time()
    xt.append((x,t))
    if len(xt) >= 2:
        dx, dt = np.diff(xt[-2:], axis=0)[0]
        print(' ... v = %.3f deg/s' % (dx/dt))
    time.sleep(1)

## This does not work.
#print('Setting speed to 1.5 deg/s')
#acu.Command('DataSets.CmdAzElVelocityTransfer8100', 'Set Azimuth',
#            '%.6f' % (1.5))

print('Measuring 3rd speed.')
pos0 = th.get_3rd(acu)
if pos0 < 90:
    target = pos0 + 30
else:
    target = pos0 - 30

xt = []
acu.go_3rd_axis(target)
while not th.check_3rd(acu, target):
    x = th.get_3rd(acu)
    t = time.time()
    xt.append((x,t))
    if len(xt) >= 2:
        dx, dt = np.diff(xt[-2:], axis=0)[0]
        print(' ... v = %.3f deg/s' % (dx/dt))
    time.sleep(1)
