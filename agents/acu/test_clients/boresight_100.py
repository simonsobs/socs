import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys
import argparse
import time

def change_boresight(boresight):
    acu_client = MatchedClient('acu1')

    acu_client.set_boresight.start(b=boresight)
    acu_client.set_boresight.wait()

if __name__ == "__main__":
    change_boresight(float(20))
