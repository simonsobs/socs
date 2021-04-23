import numpy as np
from numpy import cos, sin, tan

DEG = np.pi/180

def delta(az_el, params):
    az, el = az_el[0] * DEG, az_el[1] * DEG
    delta_az, delta_el = 0., 0.
    # 2.3.2
    delta_az += params['IA']
    delta_el += params['IE']
    # 2.3.3
    delta_el += params['TF'] * cos(el) + params['TFS'] * sin(el)
    # 2.3.4
    delta_az += (
        - params['AN'] * tan(el) * sin(az) +
        - params['AW'] * tan(el) * cos(az) +
        - params['AN2'] * tan(el) * sin(2*az) +
        - params['AW2'] * tan(el) * cos(2*az))
    delta_el += (
        - params['AN'] * cos(az) +
        + params['AW'] * sin(az) +
        - params['AN2'] * cos(az) +
        + params['AW2'] * sin(az))
    # 2.3.5
    delta_az += -params['NPAE'] * tan(el)
    # 2.3.6
    delta_az += -params['CA'] / cos(el)
    # 2.3.7
    delta_az += (
        params['AES'] * sin(az) +
        params['AEC'] * cos(az) +
        params['AES2'] * sin(2*az) +
        params['AEC2'] * cos(2*az))
    #delta_el += (
    #    params['EES'] * sin(el) +
    #    params['EEC'] * cos(el) +
    #    params['EES2'] * sin(2*el) +
    #    params['EEC2'] * cos(2*el))
    # 2.3.8, 2.3.9 - N/A.
    return np.array([delta_az, delta_el])
        
