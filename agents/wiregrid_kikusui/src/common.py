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
        pass
    else:
        logfile = open(logfilename, 'w')
        log = '#UnixTime ON/OFF time-period[sec] position[def] mode\n'
        logfile.write(log)
        logfile.flush()
        pass
    return logfile

def writelog(logfile, onoff, timeperiod=0., position=0., mode='stepping_rot'):# calibration, continuous_rot
    if timeperiod > 0.:
        log = '{:.6f} {:3s} {:8.3f} {:8.3f} {:14s}\n'.format(time.time(), onoff, timeperiod, position, mode)
        pass
    else:
        log = '{:.6f} {:3s} {:8s} {:8.3f} {:14s}\n'.format(time.time(), onoff, '--------', position, mode)
    logfile.write(log)
    logfile.flush()
    pass
