from acu import *
import time
import sys
import numpy as np
import pickle
import warnings

def time_code(t, fmt='upload'):
    if fmt == 'upload':
        fmt = '%j, %H:%M:%S'
        return time.strftime(fmt, time.gmtime(t)) + ('%.6f' % (t%1.))[1:]
    else:
        fmt = '%j'
        return time.strftime(fmt, time.gmtime(t)) + ('|%.6f' % (t % 86400))

def track_line(t, az, el, fmt='upload'):
    if fmt == 'upload':
        return '%s;%.4f;%.4f\r\n' % (time_code(t), az, el)
    if fmt == 'single':
        return '%s|%.4f|%.4f' % (time_code(t, 'single'), az, el)

def stop_cmd(acu):
    mr='Antenna.SkyAxes'
    cm = 'SetAzElMode'
    t = acu.request_command(mr, cm, 'Stop')
    print('stop_cmd')
    print(t.text)
    return mr, cm

def clear_stack(acu):
    t = acu.request_command('DataSets.CmdTimePositionTransfer', 'Clear Stack')
    print('clear_stack')
    print(t, t.text)

#def orig_track():
#    start_time = time.time() + 3.
#    az = [120 + x/10. for x in range(200)]
#    az += [140 - x/10. for x in range(200)]
#    az += [120]
#    all_lines = [track_line(start_time + i*.1, _az, 55.) for i,_az in enumerate(az)]
#    total_time = len(all_lines)*.1
#    with open('data/origtrack_times_'+str(time.time())+'.pkl','wb') as f:
#        pickle.dump({'start_time':start_time, 'all_lines':all_lines, 'total_time':total_time},f, protocol=2)
#    return all_lines, total_time

#def newtrack1():
#    start_time = time.time() + 10
#    az = [120 - x/10. for x in range(100)]
#    az += [110 + x/10. for x in range(100)]
#    az += [120]
#    all_lines = [track_line(start_time + i*.1, _az, 55.) for i,_az in enumerate(az)]
#    total_time = len(all_lines)*.1
#    with open('data/newtrack1_times_'+str(time.time())+'.pkl','wb') as f:
#        pickle.dump({'start_time':start_time, 'all_lines':all_lines, 'total_time':total_time},f, protocol=2)
#    return all_lines, total_time

#def newtrack2():
#    start_time = time.time() + 10
#    az = [120 + x/20 for x in range(200)]
#    az += [130 + x for x in np.zeros(100)]
#    az += [130 - x/20 for x in range(200)]
#    az += [120 + x for x in np.zeros(100)]
#    az += [120 + x/20 for x in range(200)]
#    az += [130.]

#    el = [55 + x for x in np.zeros(200)]
#    el += [55 + x/10 for x in range(100)]
#    el += [65 + x for x in np.zeros(200)]
#    el += [65 + x/10 for x in range(100)]
#    el += [75 + x for x in np.zeros(200)]
#    el += [75.]
    
#    all_lines = []
#    for i in range(len(az)):
#        all_lines += [track_line(start_time + i*.1, az[i], el[i])]
#    total_time = len(all_lines)*.1
#    with open('data/newtrack2_times_'+str(time.time())+'.pkl','wb') as f:
#        pickle.dump({'start_time':start_time, 'all_lines':all_lines, 'total_time':total_time},f, protocol=2) 
#    return all_lines, total_time
#tracks = {'orig_track':{'lines':orig_track()[0],'times':orig_track()[1]},'newtrack1':{'lines':newtrack1()[0], 'times':newtrack1()[1]}}

#def newtrack3():
#    start_time = time.time() + 10
#    az = [120 + x/10. for x in range(200)]
#    az += [140 + x for x in np.zeros(200)]
#    az += [140 - x/10. for x in range(200)]
#    az += [120 + x for x in np.zeros(200)]

#    all_lines = [track_line(start_time + i*.1, _az, 55.) for i,_az in enumerate(az)]
#    total_time = len(all_lines)*.1
#    return all_lines, total_time

def upload_nptrack(filename, acu):
    warnings.warn('IMPORTANT: Shut down ocsbow!!!')
    time.sleep(30)
    clear_stack(acu)
    track = np.load(filename)
    az = track[0]; el = track[1]
    start_time = time.time() + 10
    mr, cm = stop_cmd(acu)
    all_lines = [track_line(start_time + i*.1, _az, el[i]) for i,_az in enumerate(az)]
    total_time = len(all_lines)*.1
    time_range = np.linspace(start_time, start_time+total_time, len(all_lines)+1)
    with open((filename.split('.')[0])+'_'+str(time.time())+'.pkl','wb') as f:
        pickle.dump(all_lines, f, protocol=2)
    div = 480
    for j in range(div):
        print('Uploading batch %i...' % (j+1))
        print(len(all_lines)/div)
        text = ''.join(all_lines[j*int(len(all_lines)/div):(j+1)*int(len(all_lines)/div)])
        t = acu.request_upload(text)
     #   print('...', t)
       # mr, cm = stop_cmd(acu)
        t = acu.request_command(mr, cm, 'ProgramTrack')
        print(t.text)
       # current_time = time.time()
       # if current_time > time_range[(j+1)*int(len(all_lines)/div)]:
       #     warnings.warn('Upload time too late! at '+str(current_time))
        time.sleep(int(len(all_lines)/div)*.1-10)
    if len(all_lines)%div != 0:
        print('Uploading final batch (size %f)'%(len(all_lines)-len(all_lines)%div))
        text = ''.join(all_lines[len(all_lines)-(len(all_lines)%div)::])
        t = acu.request_upload(text)
        t = acu.request_command(mr, cm, 'ProgramTrack')
        print(t.text)
        print('Sleeping for time %f'%(len(all_lines)%div*.1))
        time.sleep(len(all_lines)%div*.1)
    time.sleep(10*(div+1))
    stop_cmd(acu)

def upload_nptrack_list(filename, acu):
    clear_stack(acu)
    track = np.load(filename)
    az = track[0]; el = track[1]
    start_time = time.time() + 10
    mr, cm = stop_cmd(acu)
    all_lines = []
    for i in range(len(az)):
        line_section = [track_line(start_time + j*.1, _az, el[i][j]) for j,_az in enumerate(az[i])]
        all_lines.append(line_section)
        time_section = len(line_section)*.1
        print('Uploading batch %i...' % (i+1))
        text = ''.join(line_section)
        t = acu.request_upload(text)
        t = acu.request_command(mr, cm, 'ProgramTrack')
        print(t.text)
        time.sleep(time_section)
    time.sleep(10)
    stop_cmd(acu)
    with open(filename.split('.')[0]+'_'+str(time.time())+'.pkl','wb') as f:
        pickle.dump(all_lines, f, protocol=2)
        

#def upload_stopnptrack(filename, acu):
#    clear_stack(acu)
#    track = np.load(filename)
#    az = track[0]; el = track[1]
#    start_time = time.time() + 10
#    mr, cm = stop_cmd(acu)
#    all_lines_left = [track_line(start_time + i*.05, _az, el[i]) for i,_az in enumerate(az[0:401])]
#    all_lines_right = [track_line(start_time + 2./3. + (i+400)*.05, _az, el[i+400]) for i,_az in enumerate(az[401::])]
#    total_time = len(all_lines_left)*.05 + 2./3. + len(all_lines_right)*.05
#    all_lines = all_lines_left + all_lines_right
#    with open('data/'+(filename.split('.')[0])+'_'+str(time.time())+'.pkl','wb') as f:
#        pickle.dump(all_lines, f, protocol=2)
#    div = 1
#    for j in range(div):
#        print('Uploading batch %i...' % (j+1))
#        text = ''.join(all_lines[j*int(len(all_lines)/div):(j+1)*int(len(all_lines)/div)])
#        t = acu.request_upload(text)
#        print('...', t)
       # mr, cm = stop_cmd(acu)
#        t = acu.request_command(mr, cm, 'ProgramTrack')
#        print(t.text)
#        time.sleep(total_time/div)
#    time.sleep(15)
#    stop_cmd(acu)


#def upload_track(trackname, acu):
#    clear_stack(acu)
#    tracks = {'orig_track':{'lines':orig_track()[0],'times':orig_track()[1]},'newtrack1':{'lines':newtrack1()[0], 'times':newtrack1()[1]}, 'newtrack2':{'lines':newtrack2()[0], 'times':newtrack2()[1]}, 'newtrack3':{'lines':newtrack3()[0], 'times':newtrack3()[1]}}
#    all_lines = tracks[trackname]['lines']
#    total_time = tracks[trackname]['times']
#    with open('data/'+trackname+'_'+str(time.time())+'.pkl', 'wb') as f:
#        pickle.dump(all_lines, f, protocol=2)
#    for i in range(3):
#        print('Uploading batch %i...' % (i+1))
#        text = ''.join(all_lines[i*len(all_lines):(i+1)*len(all_lines)])
#        t = acu.request_upload(text)
#        print('...', t)
#        mr, cm = stop_cmd(acu)
#        t = acu.request_command(mr, cm, 'ProgramTrack')
#        print(t.text)
#        time.sleep(total_time/3.)
#    stop_cmd(acu)

#def run_track(mr, cm, track):
    
#    t = acu.request_upload(text)
#    print('Upload: ', t)

#    time.sleep(1)
#    t = acu.request_command(mr, cm, 'ProgramTrack')
#    print(t.text)

 #   stop

#    start_time = time.time() + 10
#    az = [120 + x/10. for x in range(100)]

#    for i,_az in enumerate(az):
#        t = acu.request_command('DataSets.TimePositionTransfer','Set Time Position', track_line(start_time + i*.1, _az, 50., 'single'))
#        print(t)

if __name__ == '__main__':
    acu = AcuInterface()
    stop_cmd(acu)
#    trackname = str(sys.argv[1])
    filename = str(sys.argv[1])
    clear_stack(acu)
    upload_nptrack(filename, acu)
#    stop_cmd(acu)
