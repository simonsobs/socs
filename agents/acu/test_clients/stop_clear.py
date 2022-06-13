import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient


def stop_clear():
    acu_client = MatchedClient('acu1')
    acu_client.stop_and_clear.start()
    acu_client.stop_and_clear.wait()


if __name__ == '__main__':
    stop_clear()
