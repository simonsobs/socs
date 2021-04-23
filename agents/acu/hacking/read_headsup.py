import numpy as np
import time

def most_recent(filename):
    f = open(str(filename), 'r')
    info = f.readlines()
    f.close()

    data = {}
    info1 = info[-1].strip()
    seplines = info1.split(',')
    for i in seplines:
        qkey = i.split(':')[0]
        key = qkey.split('"')[1]
        qval = i.split(':')[1]
        try:
            val = qval.split('"')[1]
        except IndexError:
            val = qval
        try:
            data[key] = float(val)
        except ValueError:
            data[key] = val
    return data

def check_vel(data):
    ctime = data['ctime*']
    evel = data['Elevation current velocity']
    avel = data['Azimuth current velocity']
#    epos = data['Elevation current position']
#    apos = data['Azimuth current position']
    
    if evel == 0.0:
        v0e = True
    else:
        v0e = False
    if avel == 0.0:
        v0a = True
    else:
        v0a = False
        
    return v0e, v0a

def check_pos(data, az_in, el_in):
    epos = data['Elevation current position']
    apos = data['Azimuth current position']

    if epos == el_in:
        x0e = True
    else:
        x0e = False
    if apos == az_in:
        x0a = True
    else:
        x0a = False

    return x0e, x0a

def read_and_check(filename, az_in, el_in):
    time.sleep(5)
    data = most_recent(filename)
    ve,va = check_vel(data)
    while (ve == False) or (va == False):
        time.sleep(5)
        data = most_recent(filename)
        ve, va = check_vel(data)
    xe, xa = check_pos(data, az_in, el_in)
    if xe == False or xa == False:
        data = most_recent(filename)
        ve, va = check_vel(data)
        while ve == False or va == False:
            time.sleep(5)
            data = most_recent(filename)
            ve, va = check_vel(data)
        xe, xa = check_pos(data, az_in, el_in)
        if xe == False or xa == False:
            print('Failed to reach target')
            return False
        else:
            print('Reached target position')
            return True
    else:
        print('Reached target position')
        return True
