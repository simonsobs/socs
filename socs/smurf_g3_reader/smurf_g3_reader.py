import so3g
from spt3g import core
import numpy as np
import pickle
import datetime
import sys, os

def g3_to_array(g3file):
    '''
    Takes a G3 file output from the SMuRF archiver and reads to a numpy array.

    Arguments
    ---------
    g3file : full path to the G3 file
    '''
    frames = [fr for fr in core.G3File(g3file)]
    
    data=[]

    frametimes = []
    for frame in frames:
        frametime = frame['data'].times()
        frametimes.append(frametime)
    times = np.hstack(frametimes)
    
    channums = []
    for chan in frames[0]['data'].keys():
        channums.append(int(chan))
    channums.sort()
    for ch in channums:
 #       print('Adding channel %s'%ch)
        chdata = []
        for frame in frames:
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

