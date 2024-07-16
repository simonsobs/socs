# DWL drivers
from socs.agents.wiregrid_tiltsensor.drivers.dwl import DWL
# sherborne drivers
from socs.agents.wiregrid_tiltsensor.drivers.sherborne import Sherborne


def connect(ip, port, sensor_type):
    if sensor_type == 'DWL':
        tiltsensor = DWL(tcp_ip=ip, tcp_port=port, timeout=0.5, isSingle=False, verbose=0)
    elif sensor_type == 'sherborne':
        tiltsensor = Sherborne(tcp_ip=ip, tcp_port=port, reset_boot=False, timeout=0.5, verbose=0)
    else:
        raise ('Invalid tiltsensor type')
    return tiltsensor
