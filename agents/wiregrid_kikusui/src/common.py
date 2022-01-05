import os
import time
from datetime import datetime, timezone

def openlog(log_dir):
    now = datetime.now(timezone.utc)
    dateStr = now.strftime('%Y-%m-%d')

    logfilename = '{}/OCS_{}.dat'.format(log_dir, dateStr)
    if not os.path.isdir(log_dir): os.mkdir(log_dir)
    if os.path.exists(logfilename):
        logfile = open(logfilename, 'a+')
    else:
        logfile = open(logfilename, 'w')
        log = '#UnixTime ON/OFF time-period[sec] position[def] mode\n'
        logfile.write(log)
<<<<<<< HEAD
        logfile.flush()
        pass
=======
>>>>>>> 413645f62934adc2981a1bbcf19c8d99469998e3
    return logfile

def writelog(logfile, onoff, timeperiod=0., position=0., mode='stepping_rot'):# calibration, continuous_rot
    if timeperiod > 0.:
<<<<<<< HEAD
        log = '{:.6f} {:3s} {:8.3f} {:8.3f} {:14s}\n'.format(time.time(), onoff, timeperiod, position, mode)
        pass
=======
        log = '{:.6f} {:3s} {:8.3f} {:8.3f}\n'.format(time.time(), onoff, timeperiod, position)
>>>>>>> 413645f62934adc2981a1bbcf19c8d99469998e3
    else:
        log = '{:.6f} {:3s} {:8s} {:8.3f} {:14s}\n'.format(time.time(), onoff, '--------', position, mode)
    logfile.write(log)
<<<<<<< HEAD
    logfile.flush()
    pass
=======
>>>>>>> 413645f62934adc2981a1bbcf19c8d99469998e3
