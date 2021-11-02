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
    upload_track((140., 160.), 40., 1., 4, 2, 'linear_turnaround')
