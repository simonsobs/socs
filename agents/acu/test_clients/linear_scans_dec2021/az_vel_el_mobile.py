import numpy as np
import time
import ocs
from ocs import client_t, site_config
from ocs.ocs_client import OCSClient
import sys
import argparse

def upload_track(config, azpts, el, azvel, acc, ntimes, scantype, azonly=False):
     
    acu_client = OCSClient(config)
    acu_client.go_to.start(az=azpts[0], el=el, wait=1)
    acu_client.go_to.wait()
    acu_client.stop_and_clear.start()
    acu_client.stop_and_clear.wait()
    acu_client.run_specified_scan.start(azpts=azpts, el=el, azvel=azvel, acc=acc, ntimes=ntimes, scantype=scantype, azonly=azonly)
    acu_client.run_specified_scan.wait()

if __name__ == '__main__':
    NTIMES = 7
    ACC = 4
#    SET_EL = 45. 
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='ACU config (ex satp1)')
    args = parser.parse_args()
    print('Matthew scan request')
    upload_track(args.config, (280, 282), 30., 1, ACC, 13, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 1: velocity = 2, spans 20 deg (el=40, az=100-120)')
    upload_track(args.config, (100., 120.), 40., 2, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 2: velocity = 1,8 spans 18 deg (el=35, az=20-38)')
    upload_track(args.config, (20., 38.), 35., 1.8, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 3: velocity = 1,6 spans 16 deg (el=22, az=180-196)')
    upload_track(args.config, (180., 196.), 22., 1.6, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 4: velocity = 1,4 spans 14 deg (el=53, az=220-234)')
    upload_track(args.config, (220., 234.), 53., 1.4, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 5: velocity = 1,2 spans 12 deg (el=21, az=305-317)')
    upload_track(args.config, (305., 317.), 21., 1.2, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 6: velocity = 1,0 spans 10 deg (el=32, az=111-121)')
    upload_track(args.config, (111., 121.), 32., 1.0, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 7: velocity = 0,7 spans 7 deg (el=48, az=147-154')
    upload_track(args.config, (147., 154.), 48., 0.7, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 8: velocity = 0,5 spans 5 deg (el=37, az=66-71)')
    upload_track(args.config, (66., 71.), 37., 0.5, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 9: velocity = 0.3 spans 3 deg (el=44, az=38-41)')
    upload_track(args.config, (38., 41.), 44., 0.3, ACC, NTIMES, 'linear_turnaround')
    time.sleep(5)
    print('Starting scan 10: velocity = 0.1 spans 1 deg (el=25, az=242-243)')
    upload_track(args.config, (242., 243.), 25., 0.1, ACC, NTIMES, 'linear_turnaround')
    print('Completed all 10 scans!')
