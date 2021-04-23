import ocs
from ocs import client_t, site_config
from ocs.matched_client import MatchedClient


def generate_linear_test(stop_iter, az_endpoint1, az_endpoint2, az_speed, acc, el_endpoint1, el_endpoint2, el_speed):
    acu_client = MatchedClient('acu1')
    acu_client.go_to.start(az=az_endpoint1, el=el_endpoint1, wait=1)
    acu_client.go_to.wait()
#    yield dsleep(5)
    acu_client.generate_scan.start(stop_iter=stop_iter, az_endpoint1=az_endpoint1, az_endpoint2=az_endpoint2, az_speed=az_speed, acc=acc, el_endpoint1=el_endpoint1, el_endpoint2=el_endpoint2, el_speed=el_speed)
    acu_client.generate_scan.wait()

if __name__ == "__main__":
    generate_linear_test(1000, 120., 160., 1., 2., 55., 55., 0)
