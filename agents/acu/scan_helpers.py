import numpy as np
import time

def linear_turnaround_scanpoints(azpts, el, azvel, acc, ntimes):
    """
    Produces lists of times, azimuths, elevations, azimuthal velocities, elevation velocities,
    azimuth motion flags, and elevation motion flags for a finitely long azimuth scan with
    constant velocity.

    Params:
        azpts (2-tuple): The endpoints of motion in azimuth, in increasing order
        el (float): The elevation that is maintained throughout the scan
        azvel (float): Desired speed of the azimuth motion in degrees/sec
        acc (float): The turnaround acceleration in degrees/sec^2
        ntimes(int): Number of times to travel between the endpoints
    """
    turn_time = 2 * azvel / acc
    tot_time_dir = float((abs(azpts[1] - azpts[0])) / azvel)
    time1 = np.linspace(0, tot_time_dir, int(tot_time_dir*10.))
    conctimes = list(time1)

    az1 = np.linspace(azpts[0], azpts[1], int(tot_time_dir*10.))
    concaz = list(az1)

    el1 = np.linspace(el, el, int(tot_time_dir*10.))
    concel = list(el1)

    va1 = np.zeros(int(tot_time_dir*10.)) + azvel
    concva = list(va1)
    ve1 = np.zeros(int(tot_time_dir*10.))
    concve = list(ve1)

    azflags = [1 for i in range(int(tot_time_dir*10.)-1)]
    azflags += [2]
    all_azflags = azflags

    elflags = [0 for i in range(int(tot_time_dir*10.))]
    all_elflags = elflags

    for n in range(1, ntimes):
        last_time_prevdir = conctimes[-1]
        time2 = list(np.linspace(last_time_prevdir + turn_time, last_time_prevdir + turn_time + tot_time_dir, int(tot_time_dir*10.)))

        if n%2 != 0:
            new_az = list(np.linspace(azpts[1], azpts[0], int(tot_time_dir*10.)))
            new_va = list(np.zeros(int(tot_time_dir*10.)) - azvel)
        else:
            new_az = list(np.linspace(azpts[0], azpts[1], int(tot_time_dir*10.)))
            new_va = list(np.zeros(int(tot_time_dir*10.)) + azvel)

        for k in range(len(time2)):
            conctimes.append(time2[k])
            concaz.append(new_az[k])
            concel.append(el1[k])
            concva.append(new_va[k])
            concve.append(ve1[k])
            all_azflags.append(azflags[k])
            all_elflags.append(elflags[k])

    concva[-1] = 0.0
    all_azflags[-1] = 0

    return conctimes, concaz, concel, concva, concve, all_azflags, all_elflags

def from_file(filename):
    """
    Produces properly formatted lists of times, azimuth and elevation locations, 
    azimuth and elevation velocities, and azimuth and elevation motion flags for 
    a finitely long scan from a numpy file. Numpy file must be formatted as an array 
    of arrays in the order [times, azimuths, elevations, azimuth velocities, elevation 
    velocities]

    Params:
        filename (str): Full path to the numpy file containing scan parameter array
    """
    info = np.load(filename)
    conctimes = info[0]
    concaz = info[1]
    concel = info[2]
    concva = info[3]
    concve = info[4]
    az_flags = np.array([0 for x in range(len(conctimes))])
    el_flags = az_flags
    return conctimes, concaz, concel, concva, concve, az_flags, el_flags

def write_lines(conctimes, concaz, concel, concva, concve, az_flags, el_flags):
    """
    Produces a list of lines in the format necessary to upload to the ACU to complete a scan. 
    Params are the outputs of from_file or linear_turnaround_scanpoints.

    Params:
        conctimes (list): List of times starting at 0 for the ACU to reach associated positions
        concaz (list): List of azimuth positions associated with times
        concel (list): List of elevation positions associated with times
        concva (list): List of azimuth velocities associated with times
        concve (list): List of elevation velocities associated with times
        az_flags (list): List of flags associated with azimuth motions at associated times
        el_flags (list): List of flags associated with elevation motions at associated times
    """
    fmt = '%j, %H:%M:%S'
    start_time = time.time() + 10.
    true_times = [start_time + i for i in conctimes]
    fmt_times = [time.strftime(fmt, time.gmtime(t)) + ('%.6f' % (t%1.))[1:] for t in true_times]

    all_lines = [('%s;%.4f;%.4f;%.4f;%.4f;%i;%i\r\n' % (fmt_times[n], concaz[n], concel[n], concva[n], concve[n], az_flags[n], el_flags[n])) for n in range(len(fmt_times))]

    return all_lines

def write_generator_lines(conctimes, concaz, concel, concva, concve, az_flags, el_flags):
    """
    Produces a list of lines in the format necessary to upload to the ACU to complete a 
    generated scan. Params are the outputs of generate.

    Params:
        conctimes (list): List of times starting at most recently used time for the ACU 
                          to reach associated positions
        concaz (list): List of azimuth positions associated with times
        concel (list): List of elevation positions associated with times
        concva (list): List of azimuth velocities associated with times
        concve (list): List of elevation velocities associated with times
        az_flags (list): List of flags associated with azimuth motions at associated times
        el_flags (list): List of flags associated with elevation motions at associated times
    """
    fmt = '%j, %H:%M:%S'
    start_time = 10.
    true_times = [start_time + i for i in conctimes]
    fmt_times = [time.strftime(fmt, time.gmtime(t)) + ('%.6f' % (t%1.))[1:] for t in true_times]

    all_lines = [('%s;%.4f;%.4f;%.4f;%.4f;%i;%i\r\n' % (fmt_times[n], concaz[n], concel[n], concva[n], concve[n], az_flags[n], el_flags[n])) for n in range(len(fmt_times))]
    return all_lines

def generate(stop_iter, az_endpoint1, az_endpoint2, az_speed, acc, el_endpoint1, el_endpoint2, el_speed):
    """
    Python generator to produce times, azimuth and elevation positions, azimuth and elevation 
    velocities, azimuth and elevation flags for arbitrarily long scans. For development, this 
    is limited to constant-velocity azimuth scans.

    Params:
        stop_iter (int): maximum number of times the generator should produce new points.
        az_endpoint1 (float): the azimuth endpoint at which to start the scan
        az_endpoint2 (float): the second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the endpoints
        el_endpoint1 (float): elevation endpoint at which to start the motion
        el_endpoint2 (float): second elevation endpoint of the scan. For development, this 
                              must be equal to el_endpoint1.
        el_speed (float): speed of the elevation motion. For development, set to 0.0
    """
    az_min = min(az_endpoint1, az_endpoint2)
    az_max = max(az_endpoint1, az_endpoint2)
    t0 = time.time() + 10.
    t = 0
    turntime = 2.0 * az_speed / acc
    az = az_endpoint1
    el = el_endpoint1
    daz = 0.1 * az_speed
    el_vel = el_speed
    az_flag = 0
    if az < az_endpoint2:
        increasing = True
        az_vel = az_speed
    elif az > az_endpoint2:
        increasing = False
        az_vel = -1*az_speed
    else:
        print('Error: need two different motion endpoints.')
        return
    for i in range(stop_iter):
        point_block = [[],[],[],[],[],[],[]]
        for j in range(500):
            if increasing:
                if round(az, 4) <= (az_max-daz):
                    t += 0.1
                    az += daz
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                elif round(az, 4) == (az_max-daz):
                    t += 0.1
                    az += daz
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = True
                elif round(az, 4) == az_max:
                    t += 0.1 + turntime
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
            else:
                if round(az, 4) > az_min:
                    t += 0.1
                    az -= daz
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                elif round(az, 4) == (az_min + daz):
                    t += 0.1
                    az -= daz
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = False
                elif round(az, 4) == az_min:
                    t += 0.1 + turntime
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
            point_block[0].append(t + t0)
            point_block[1].append(az)
            point_block[2].append(el)
            point_block[3].append(az_vel)
            point_block[4].append(el_vel)
            point_block[5].append(az_flag)
            point_block[6].append(el_flag)
        yield write_generator_lines(point_block[0], point_block[1], point_block[2], point_block[3], point_block[4], point_block[5], point_block[6])


if __name__ == "__main__":
    print(time.time())
    times, azs, els, vas, ves, azf, elf = linear_turnaround_scanpoints((120., 130.), 55., 1., 4, 2000)
    print(time.time())
    print(len(times))
    print(times[0], azs[0], els[0], vas[0], ves[0], azf[0], elf[0])
    lines = write_lines(times, azs, els, vas, ves, azf, elf)
    print(lines[20])
