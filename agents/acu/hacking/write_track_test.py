from acu import *
import time
import pickle

def time_code(t, fmt='upload'):
    if fmt == 'upload':
        fmt = '%j, %H:%M:%S'
        return time.strftime(fmt, time.gmtime(t)) + ('%.6f' % (t%1.))[1:]
    else:
        fmt = '%j'
        return time.strftime(fmt, time.gmtime(t)) + ('|%.6f' % (t % 86400))

    #day = time.gmtime(t).tm_yday
    #dayf = (t/86400.) % 1.
    #return (day, dayf)

def track_line(t, az, el, fmt='upload'):
    if fmt == 'upload':
        return '%s;%.4f;%.4f\r\n' % (time_code(t), az, el)
    if fmt == 'single':
        return '%s|%.4f|%.4f' % (time_code(t, 'single'), az, el)

acu = AcuInterface()

# Stop mode.
mr='Antenna.SkyAxes'
cm = 'SetAzElMode'
t = acu.request_command(mr, cm, 'Stop')
print(t.text)

# Clear the stack.
t = acu.request_command('DataSets.CmdTimePositionTransfer', 'Clear Stack')
print(t, t.text)

# Upload some points.
start_time = time.time() + 3.
az = [120 + x/10. for x in range(200)]
az += [140 - x/10. for x in range(200)]
az += [120]

all_lines = [track_line(start_time + i*.1, _az, 55.)
                for i,_az in enumerate(az)]

print('Uploading ')
text = ''.join(all_lines[:5]) + '\r\n'
t = acu.request_upload(text)
print(' ...', t)
#print('Request data was:')
#t = acu.request_command(mr, cm, 'ProgramTrack')
#print(t.text)
#time.sleep(total_time/3.)


## As of ICD 2.0, this _should_ work but appears not to.  It was
## always slow -- appears to be handled in the same 5 Hz loop as the
## other queries.
#if 0:
    ## Uploading individual points.
    #
    # This is slow -- each query takes almost 1 second.  These points show
    # up in /GetPtStack output, whereas POST-ed files seem not to.
#    start_time = time.time() + 10
#    az = [120 + x/10. for x in range(100)]

#    for i,_az in enumerate(az):
#        t = acu.request_command('DataSets.TimePositionTransfer',
#                                'Set Time Position',
#                                track_line(start_time + i*.1, _az, 50.,'single'))
#        print(t)

