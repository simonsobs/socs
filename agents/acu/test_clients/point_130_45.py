import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient
import sys
import argparse
import time


def point_there(azimuth, elevation, waittime):
    acu_client = MatchedClient('acu1')

    acu_client.go_to.start(az=azimuth, el=elevation, wait=waittime)
    acu_client.go_to.wait()


if __name__ == "__main__":
    point_there(float(130), float(25), 1)
