import numpy as np
import time
import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys

def upload_track(scantype, filename):

    acu_client = MatchedClient('acu1')
    acu_client.run_specified_scan.start(scantype=scantype, filename=filename)
    acu_client.run_specified_scan.wait()

if __name__ == "__main__":
    upload_track('from_file', '/home/ocs/git/vertex-acu-agent/test_clients/npyfiles/sat_test_v2a6.npy')
