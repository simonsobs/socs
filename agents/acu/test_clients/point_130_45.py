import ocs
from ocs import client_t, site_config
from ocs.ocs_client import OCSClient
import sys
import argparse
import time

def point_there(config, azimuth, elevation, waittime=1):
    acu_client = OCSClient(config)

    acu_client.go_to.start(az=azimuth,el=elevation, wait=waittime)
    acu_client.go_to.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='ACU config (ex acu-satp1)')
    parser.add_argument('--az', default=130., help='azimuth value (int)')
    parser.add_argument('--el', default=45., help='elevation value (int)')
    args = parser.parse_args()
    point_there(args.config, args.az, args.el)
#    point_there(float(130), float(25), 1)
