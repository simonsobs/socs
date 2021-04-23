import numpy as np
import time
import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys

def upload_track(scantype, testing, azpts, el, azvel, acc, ntimes):
     
    acu_client = MatchedClient('acu1')
    acu_client.go_to.start(az=azpts[0], el=el, wait=1)
    acu_client.go_to.wait()
  #  acu_client.go_to.stop()
    acu_client.run_specified_scan.start(scantype=scantype, testing=testing, azpts=azpts, el=el, azvel=azvel, acc=acc, ntimes=ntimes)
    acu_client.run_specified_scan.wait()

if __name__ == '__main__':
    upload_track('linear_turnaround_sameends', True, (120., 160.), 35., 1., 4, 3)
