import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient


def find_az_stop(startaz, startel, endaz, endel):
    acu_client = MatchedClient('acu1')
    acu_client.go_to.start(az=startaz, el=startel)
    acu_client.go_to.wait()
    acu_client.find_az_stop_point.start(az=endaz)
    acu_client.find_az_stop_point.wait()
    acu_client.find_el_stop_point.start(el=endel)
    acu_client.find_el_stop_point.wait()


if __name__ == "__main__":
    find_az_stop(80., 30., 160., 45.)
