import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys
import argparse
import time

def point_there(config, azimuth=120., elevation=35., waittime=1):
    acu_client = MatchedClient(config)
#    acu_client.stop_and_clear.start()
#    acu_client.stop_and_clear.wait()
#    time.sleep(1)
    acu_client.go_to.start(az=azimuth,el=elevation, wait=waittime)
    acu_client.go_to.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='ACU config (ex satp1)')
    parser.add_argument('--az', default=120., help='azimuth value (int)')
    parser.add_argument('--el', default=35., help='elevation value (int)')
    args = parser.parse_args()
    point_there(args.config, args.az, args.el)
#    point_there(float(120), float(35), 1)
