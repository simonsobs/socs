import numpy as np
import time

def linear_turnaround_scanpoints(azpts, el, azvel, acc, ntimes):
    """
    Produces lists of times, azimuths, elevations, azimuthal velocities, elevation velocities,
    azimuth motion flags, and elevation motion flags for a finitely long azimuth scan with
    constant velocity. Scan begins at the first azpts value.

    Parameters:
        azpts (2-tuple): The endpoints of motion in azimuth, where the first point
                         is the start position of the scan.
        el (float): The elevation that is maintained throughout the scan
        azvel (float): Desired speed of the azimuth motion in degrees/sec
        acc (float): The turnaround acceleration in degrees/sec^2
        ntimes(int): Number of times to travel between the endpoints. ntimes = 1
                     corresponds to a scan from, ex., left to right, and does not
                     return to left.

    Returns:
        tuple of lists (times, azimuths, elevations, azimuth veolicities, elevation velocities, 
                        azimuth flags, elevation flags)
    """
    if float(azvel) == 0.0:
        print('Azimuth velocity is zero, invalid scan parameter')
        return False
    if float(acc) == 0.0:
        print('Acceleration is zero, unable to calculate turnaround')
        return False
    turn_time = 2 * azvel / acc
    tot_time_dir = float((abs(azpts[1] - azpts[0])) / azvel)
    num_dirpoints = int(tot_time_dir*10.)
    if num_dirpoints < 2:
        print('Scan is too short to run')
        return False
    sect_start_time = 0.0
    conctimes = []
    concaz = []
    el1 = np.linspace(el, el, num_dirpoints)
    concel = list(el1)
    concva = []
    ve1 = np.zeros(num_dirpoints)
    concve = list(ve1)

    # Flag values:
    # 0 : unidentified portion of the scan
    # 1 : constant velocity, with the next point at the same velocity
    # 2 : final point before a turnaround
    azflags = [1 for i in range(num_dirpoints-1)]
    azflags += [2]
    all_azflags = []

    elflags = [0 for i in range(num_dirpoints)]
    all_elflags = []

    for n in range(ntimes):
        #print(str(n)+' '+str(sect_start_time))
        end_dir_time = sect_start_time + tot_time_dir
        time_for_section = np.linspace(sect_start_time, end_dir_time, num_dirpoints)
        if n%2 != 0:
            new_az = np.linspace(azpts[1], azpts[0], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + np.sign(azpts[0]-azpts[1])*azvel
        else:
            new_az = np.linspace(azpts[0], azpts[1], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + np.sign(azpts[1]-azpts[0])*azvel

        conctimes.extend(time_for_section)
        concaz.extend(new_az)
        concel.extend(el1)
        concva.extend(new_va)
        concve.extend(ve1)
        all_azflags.extend(azflags)
        all_elflags.extend(elflags)
        sect_start_time = time_for_section[-1] + turn_time

#    concva[-1] = 0.0
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

    Returns:
        tuple of lists (times, azimuths, elevations, azimuth veolicities, elevation velocities, 
                        azimuth flags, elevation flags)

    NOTE: Flags can be set in the numpy file (0=unspecified, 1=constant velocity, 2=last
          point before turnaround). If flags are not set in the file, all flags are set
          to 0 to accommodate non-linear scans
    """
    info = np.load(filename)
    if len(info) < 5:
        print('Not enough information. Make sure you have specified time, azimuth, elevation, '\
              'azimuth velocity, and elevation velocity') 
    conctimes = info[0]
    concaz = info[1]
    concel = info[2]
    concva = info[3]
    concve = info[4]
    if len(info) == 5:
        az_flags = np.array([0 for x in range(len(conctimes))])
        el_flags = az_flags
    elif len(info) == 7:
        az_flags = info[5]
        el_flags = info[6]
    else:
        print('File has too many parameters!')
        return False
    return conctimes, concaz, concel, concva, concve, az_flags, el_flags

def ptstack_format(conctimes, concaz, concel, concva, concve, az_flags, el_flags, start_offset=10., generator=False):
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
        generator (bool): Toggles the start time. When true, start time is 10, otherwise
                          start time is time.time() + 10

    Returns:
        all_lines: List of lines in the correct format to upload to the ACU.
    """
    fmt = '%j, %H:%M:%S'
    if generator:
        start_time = start_offset
    else:
        start_time = time.time() + start_offset
    true_times = [start_time + i for i in conctimes]
    fmt_times = [time.strftime(fmt, time.gmtime(t)) + ('{tt:.6f}'.format(tt=t%1.))[1:] for t in true_times]

    all_lines = [('{ftime}; {az:.6f}; {el:.6f}; {azvel:.4f}; {elvel:.4f}; {azflag}; {elflag}\r\n'.format(ftime=fmt_times[n], az=concaz[n], el=concel[n], azvel=concva[n], elvel=concve[n], azflag=az_flags[n], elflag=el_flags[n])) for n in range(len(fmt_times))]

    return all_lines

def generate_linear_turnaround(az_endpoint1, az_endpoint2, az_speed, acc, el_endpoint1, el_endpoint2, el_speed, stop_iter=float('inf'), wait_to_start=10., step_time=0.1, batch_size=500, ptstack_fmt=True):
    """
    Python generator to produce times, azimuth and elevation positions, azimuth and elevation 
    velocities, azimuth and elevation flags for arbitrarily long constant-velocity azimuth 
    scans.

    Params:
        az_endpoint1 (float): the azimuth endpoint at which to start the scan
        az_endpoint2 (float): the second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the endpoints
        el_endpoint1 (float): elevation endpoint at which to start the motion
        el_endpoint2 (float): second elevation endpoint of the scan. For development, this 
                              must be equal to el_endpoint1.
        el_speed (float): speed of the elevation motion. For development, set to 0.0
        stop_iter (float or int): sets the number of iterations for the generator.
                                  Default value is infinity.
        wait_to_start (float): number of seconds to wait between time.time() and the real 
                               start time. Default is 10 seconds.
        step_time (float): time between points on the constant-velocity parts of the motion.
                           Default value is 0,1 seconds. Minimum value is 0.05 seconds.
        batch_size (int): number of values to produce in each iteration. Default is 500.
        ptstack_fmt (bool): determine whether values are produced with the necessary format
                            to upload to the ACU. If False, this function will produce 
                            lists of time, azimuth, elevation, azimuth velocity, elevation
                            velocity, azimuth flags, and elevation flags. Default is True.
    """
    az_min = min(az_endpoint1, az_endpoint2)
    az_max = max(az_endpoint1, az_endpoint2)
    t0 = time.time() + wait_to_start
    t = 0
    turntime = 2.0 * az_speed / acc
    az = az_endpoint1
    el = el_endpoint1
    if step_time < 0.05:
        raise ValueError('Time step size too small, must be at least 0.05 seconds')
    daz = round(step_time*az_speed, 4)
    el_vel = el_speed
    az_flag = 0
    if az < az_endpoint2:
        increasing = True
        az_vel = az_speed
    elif az > az_endpoint2:
        increasing = False
        az_vel = -1*az_speed
    else:
        raise ValueError('Need two different motion endpoints')
    az_remainder = (az_max - az_min) % daz
    if az_remainder == 0.0:
        leftover_az = 0.0
        leftover_time = 0.0
    else:
        leftover_az = round(az_remainder, 4)
        leftover_time = az_remainder / az_speed
    i = 0
    while i < stop_iter:
        i += 1
        point_block = [[],[],[],[],[],[],[]]
        for j in range(batch_size):
            t += step_time
            if increasing:
                if round(az, 4) <= (az_max-(2*daz+leftover_az)):
                    az += daz
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                elif round(az, 4) == az_max:
                    t += turntime
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                elif round(az, 4) == (az_max-(daz+leftover_az)):
                    az = az_max
                    t += leftover_time
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = True
            else:
                if round(az, 4) >= (az_min + (2*daz+leftover_az)):
                    az -= daz
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                elif round(az, 4) == az_min:
                    t += turntime
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                elif round(az, 4) == az_min+(daz+leftover_az):
                    az = az_min
                    t += leftover_time
                    az_vel = -1*az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = False
            point_block[0].append(t + t0)
            point_block[1].append(az)
            point_block[2].append(el)
            point_block[3].append(az_vel)
            point_block[4].append(el_vel)
            point_block[5].append(az_flag)
            point_block[6].append(el_flag)
        if ptstack_fmt:
            yield ptstack_format(point_block[0], point_block[1], point_block[2], point_block[3], point_block[4], point_block[5], point_block[6], generator=True)
        else:
            yield (point_block[0], point_block[1], point_block[2], point_block[3], point_block[4], point_block[5], point_block[6])


if __name__ == "__main__":
    print(time.time())
    times, azs, els, vas, ves, azf, elf = linear_turnaround_scanpoints((120., 130.), 55., 1., 4, 2000)
    print(time.time())
