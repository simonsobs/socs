import argparse
import ocs
from ocs import client_t, site_config
from ocs.ocs_client import OCSClient

def stop_clear(config):
    acu_client = OCSClient(config)
    acu_client.stop_and_clear.start()
    acu_client.stop_and_clear.wait()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', help='ACU config (ex acu-satp1)')
    args = parser.parse_args()
    stop_clear(args.config)
