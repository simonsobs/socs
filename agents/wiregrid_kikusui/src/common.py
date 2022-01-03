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
        log = '#UnixTime ON/OFF time-period[sec] position[def]\n'
        logfile.write(log)
    return logfile

def writelog(logfile, onoff, timeperiod=0., position=0.):
    if timeperiod > 0.:
        log = '{:.6f} {:3s} {:8.3f} {:8.3f}\n'.format(time.time(), onoff, timeperiod, position)
    else:
        log = '{:.6f} {:3s} {:8s} {:8.3f}\n'.format(time.time(), onoff, '--------', position)
    logfile.write(log)
