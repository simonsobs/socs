import ocs
from ocs import client_t, site_config
from ocs.ocs_client import OCSClient
import sys
import argparse
import time

def change_boresight(config, boresight):
    acu_client = OCSClient(config)

    acu_client.set_boresight.start(b=boresight)
    acu_client.set_boresight.wait()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    args = parser.parse_args()
    change_boresight(args.config, float(12))
