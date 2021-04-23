import time
import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys

def upload_track(scantype, azpts, el, azvel, acc, ntimes):
    acu_client = MatchedClient('acu1')
    acu_client.run_specified_scan.start(scantype=scantype, azpts=azpts, el=el, azvel=azvel, acc=acc, ntimes=ntimes)
    acu_client.run_specified_scan.wait()

if __name__ == '__main__':
    upload_track('linear_turnaround_sameends', (120., 140.), 55., 1., 2, 6)
