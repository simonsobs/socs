import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient

def find_az_stop(az, el):
    acu_client = MatchedClient('acu1')
    acu_client.find_az_stop_point.start(az=az)
    acu_client.find_az_stop_point.wait()
    acu_client.find_el_stop_point.start(el=el)
    acu_client.find_el_stop_point.wait()

if __name__ == "__main__":
    find_az_stop(173., 58.)
