# OCS-free testing of aculib twisted backend.

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, Deferred
import twisted.web.client as tclient
from autobahn.twisted.util import sleep as dsleep

# Temporary hack for importing aculib during dev.
#import os, sys
#here = os.path.split(__file__)[0]
#sys.path.append(os.path.join(here, '../'))
import time

import aculib
from aculib.twisted_backend import TwistedHttpBackend

web_agent = tclient.Agent(reactor)
tclient._HTTP11ClientFactory.noisy = False

acu = aculib.AcuControl('guess', backend=TwistedHttpBackend(web_agent))

@inlineCallbacks
def test_move():
    print('Running test_move')

#    web_agent = tclient.Agent(reactor)
#    tclient._HTTP11ClientFactory.noisy = False

#    acu = aculib.AcuControl(
#        'guess', backend=TwistedHttpBackend(web_agent))

    d = yield acu.go_to(110,70)
    print(d)
    print('sleeping')
    yield dsleep(30)
    d = yield acu.stop()
    print(d)
    print('exiting')
    print('Mode is', (yield acu.mode()))
    reactor.stop()

@inlineCallbacks
def test_monitor():
    print('Running test_monitor')
    t = 0
    while t<5:
        d = yield acu.http.Values('DataSets.StatusGeneral8100')
        print(d['Time'], list(d.keys()))
        yield dsleep(1)
        t += 1
    print('exiting')
    reactor.stop()

@inlineCallbacks
def test_track():
    def time_code(t, fmt='upload'):
        if fmt == 'upload':
            fmt = '%j, %H:%M:%S'
            return time.strftime(fmt, time.gmtime(t)) + ('%.6f' % (t%1.))[1:]
        else:
            fmt = '%j'
            return time.strftime(fmt, time.gmtime(t)) + ('|%.6f' % (t % 86400))
    def track_line(t, az, el, fmt='upload'):
        if fmt == 'upload':
            return '%s;%.4f;%.4f\r\n' % (time_code(t), az, el)
        if fmt == 'single':
            return '%s|%.4f|%.4f' % (time_code(t, 'single'), az, el)

    # Upload some points.
    start_time = time.time() + 3.
    dt = .1
    n = 100
    az = [120 + x/10. for x in range(n)]
    az += [140 - x/10. for x in range(n)]
    az += [120]

    all_lines = [track_line(start_time + i*dt, _az, 55.)
                    for i,_az in enumerate(az)]
    total_time = len(all_lines) * dt
    text = ''.join(all_lines)
    print('Uploading test_track')
    x = yield acu.UploadPtStack(text)
    print('  returned ', x)
#    t = acu.request_upload(text)
#    print(' ...', t)
#    t = acu.request_command(mr, cm, 'ProgramTrack')
#    print(t.text)
#    time.sleep(total_time/3.)
#

@inlineCallbacks
def test_clear_stack():
    x = yield acu.Command('DataSets.CmdTimePositionTransfer',
                      'Clear Stack')
    print(x)
    reactor.stop()

#reactor.callLater(1, test_monitor)
#reactor.callLater(1, test_move)
#reactor.callLater(1, test_track)
reactor.callLater(.1, test_clear_stack)
reactor.run()
