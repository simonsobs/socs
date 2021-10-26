import numpy as np
import time
import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys

def upload_track(azpts, el, azvel, acc, ntimes, scantype):
     
    acu_client = MatchedClient('acu1')
    acu_client.go_to.start(az=azpts[0], el=el, wait=1)
    acu_client.go_to.wait()
    acu_client.stop_and_clear.start()
    acu_client.stop_and_clear.wait()
    acu_client.run_specified_scan.start(azpts=azpts, el=el, azvel=azvel, acc=acc, ntimes=ntimes, scantype=scantype)
    acu_client.run_specified_scan.wait()

if __name__ == '__main__':
    print('Starting scan 1: velocity = 2, spans az(100, 120)')
    upload_track((100., 120.), 40., 2, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 2: velocity = 1,8 spans az(100, 118)')
    upload_track((100., 118.), 40., 1.8, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 3: velocity = 1,6 spans az(100, 116)')
    upload_track((100., 116.), 40., 1.6, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 4: velocity = 1,4 spans az(100, 114)')
    upload_track((100., 114.), 40., 1.4, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 5: velocity = 1,2 spans az(100, 112)')
    upload_track((100., 112.), 40., 1.8, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 6: velocity = 1,0 spans az(100, 110)')
    upload_track((100., 110.), 40., 1.0, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 7: velocity = 0,7 spans az(100, 107)')
    upload_track((100., 107.), 40., 0.7, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 8: velocity = 0,5 spans az(100, 105)')
    upload_track((100., 105.), 40., 0.5, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 9: velocity = 0.3 spans az(100, 103)')
    upload_track((100., 103.), 40., 0.3, 4, 3, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 10: velocity = 0.1 spans az(100, 101)')
    upload_track((100., 101.), 40., 0.1, 4, 3, 'linear_turnaround')
    print('Completed all 10 scans!')
