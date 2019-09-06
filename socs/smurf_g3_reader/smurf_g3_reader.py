import so3g
from spt3g import core
import numpy as np
import pickle
import datetime
import sys, os

def g3_to_dict(g3file):
    
    frames = [fr for fr in core.G3File(g3file)]
    
    data=[]

    times = []
    for frame in frames:
        for time in frame['data'].times():
            times.append(str(time))
    times = np.asarray(times)
    
    channums = []
    for chan in frames[0]['data'].keys():
        channums.append(int(chan))
    channums.sort()
    for ch in channums:
        print('Adding channel %s'%ch)
        chdata = []
        for frame in frames:
            for i in range(len(frame['data'][str(ch)])):
                chdata.append(frame['data'][str(ch)][i])
        chdata = np.asarray(chdata)
        data.append(chdata)

    data = np.asarray(data)
    return times, data


if __name__ == '__main__':
    g3file = sys.argv[1]
    times, data = g3_to_dict(g3file)
    newfile_name = g3file.strip('.g3')
    with open(newfile_name+'.pkl','wb') as f:
        pickle.dump({'times':times, 'data':data},f)
    f.close()

