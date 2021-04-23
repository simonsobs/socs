import numpy as np

def get_positions(acu):
    stat = acu.Values('DataSets.StatusGeneral8100')
    return np.array([float(stat['Azimuth current position']),
                     float(stat['Elevation current position'])])

def check_positions(acu, az, el, tol=1e-3):
    pos_now = get_positions(acu)
    return ((pos_now - [az, el])**2).sum() < tol**2

def get_3rd(acu):
    stat = acu.Values('DataSets.Status3rdAxis')
    return stat['3rd axis current position']

def check_3rd(acu, pos, tol=1e-3):
    pos_now = get_3rd(acu)
    return abs(pos_now - pos) < tol

def check_remote(acu):
    ident, param = 'DataSets.StatusSATPDetailed8100', 'ACU in remote mode'
    return acu.Values(ident)[param]
