import so3g
from spt3g import core
import numpy as np
import pickle
import datetime, time
import sys, os

def g3_to_array(g3file):
    """
    Takes a G3 file output from the SMuRF archiver and reads to a numpy array.

    Parameters
    ----------
    g3file : full path to the G3 file
    
    Returns
    -------
    times : array of G3Time objects
    data : array of arrays, where each internal array is a SMuRF channel
    """
    frames = [fr for fr in core.G3File(g3file)]
    
    data=[]

    frametimes = []
    for frame in frames:
        if frame.type == core.G3FrameType.Scan:
            frametime = frame['data'].times()
            frametimes.append(frametime)
    strtimes = np.hstack(frametimes)
    
    times = []
    for strt in strtimes:
        t=core.G3Time(strt).time/core.G3Units.s
        times.append(t)
    times = np.asarray(times)
    
    channums = []
    
    if frames[1].type == core.G3FrameType.Scan:
        for chan in frames[1]['data'].keys():
            channums.append(int(chan))
    else:
        for chan in frames[2]['data'].keys():
            channums.append(int(chan))
    channums.sort()
    for ch in channums:
 #           print('Adding channel %s'%ch)
        chdata = []
        for frame in frames:
            if frame.type == core.G3FrameType.Scan:
                framedata = frame['data'][str(ch)]
                chdata.append(framedata)
        chdata_all = np.hstack(chdata)
        data.append(chdata_all)

    data = np.asarray(data)
    return times, data


if __name__ == '__main__':
    g3file = sys.argv[1]
    times, data = g3_to_array(g3file)
    newfile_name = g3file.split('/')[-1].strip('.g3')
    with open(newfile_name+'.pkl','wb') as f:
        pickle.dump({'times':times, 'data':data},f)
    f.close()

