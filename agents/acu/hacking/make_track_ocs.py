import numpy as np

def azonly_linear_oneway(trackname, azpts, el, azvel = 1.0, elvel = 0.0):
    total_time = (azpts[1]-azpts[0])/azvel
    azs = np.linspace(azpts[0], azpts[1], total_time*10)
    els = np.linspace(el, el, total_time*10)
    times = np.linspace(0.0, total_time, total_time*10)
#    return np.array([times, azs, els])
    np.save(str(trackname), np.array([times, azs, els])
