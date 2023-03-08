import math
import time

import numpy as np


def constant_velocity_scanpoints(azpts, el, azvel, acc, ntimes):
    """
    Produces lists of times, azimuths, elevations, azimuthal velocities,
    elevation velocities, azimuth motion flags, and elevation motion flags
    for a finitely long azimuth scan with constant velocity. Scan begins
    at the first azpts value.

    Parameters:
        azpts (2-tuple): The endpoints of motion in azimuth, where the
            first point is the start position of the scan.
        el (float): The elevation that is maintained throughout the scan
        azvel (float): Desired speed of the azimuth motion in degrees/sec
        acc (float): The turnaround acceleration in degrees/sec^2
        ntimes(int): Number of times to travel between the endpoints.
            ntimes = 1 corresponds to a scan from, ex., left to right, and does not
            return to left.

    Returns:
        tuple of lists : (times, azimuths, elevations, azimuth veolicities,
        elevation velocities, azimuth flags, elevation flags)
    """
    if float(azvel) == 0.0:
        print('Azimuth velocity is zero, invalid scan parameter')
        return False
    if float(acc) == 0.0:
        print('Acceleration is zero, unable to calculate turnaround')
        return False
    turn_time = 2 * azvel / acc
    tot_time_dir = float((abs(azpts[1] - azpts[0])) / azvel)
    num_dirpoints = int(tot_time_dir * 10.)
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
    azflags = [1 for i in range(num_dirpoints - 1)]
    azflags += [2]
    all_azflags = []

    elflags = [0 for i in range(num_dirpoints)]
    all_elflags = []

    for n in range(ntimes):
        # print(str(n)+' '+str(sect_start_time))
        end_dir_time = sect_start_time + tot_time_dir
        time_for_section = np.linspace(sect_start_time, end_dir_time,
                                       num_dirpoints)
        if n % 2 != 0:
            new_az = np.linspace(azpts[1], azpts[0], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + \
                np.sign(azpts[0] - azpts[1]) * azvel
        else:
            new_az = np.linspace(azpts[0], azpts[1], num_dirpoints)
            new_va = np.zeros(num_dirpoints) + \
                np.sign(azpts[1] - azpts[0]) * azvel

        conctimes.extend(time_for_section)
        concaz.extend(new_az)
        concel.extend(el1)
        concva.extend(new_va)
        concve.extend(ve1)
        all_azflags.extend(azflags)
        all_elflags.extend(elflags)
        sect_start_time = time_for_section[-1] + turn_time

    all_azflags[-1] = 0

    return conctimes, concaz, concel, concva, concve, all_azflags, \
        all_elflags


def from_file(filename):
    """
    Produces properly formatted lists of times, azimuth and elevation
    locations, azimuth and elevation velocities, and azimuth and elevation
    motion flags for a finitely long scan from a numpy file. Numpy file
    must be formatted as an array of arrays in the order [times, azimuths,
    elevations, azimuth velocities, elevation velocities]

    Parameters:
        filename (str): Full path to the numpy file containing scan
            parameter array

    Returns:
        tuple of lists: (times, azimuths, elevations, azimuth velocities,
        elevation velocities, azimuth flags, elevation flags)

    NOTE: Flags can be set in the numpy file (0=unspecified, 1=constant
    velocity, 2=last point before turnaround). If flags are not set in
    the file, all flags are set to 0 to accommodate non-linear scans
    """
    info = np.load(filename)
    if len(info) < 5:
        raise TypeError('Not enough fields in numpy file! Expected '
                        '5 fields.')
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


def ptstack_format(conctimes, concaz, concel, concva, concve, az_flags,
                   el_flags, start_offset=3., generator=False):
    """
    Produces a list of lines in the format necessary to upload to the ACU
    to complete a scan. Params are the outputs of from_file,
    constant_velocity_scanpoints, or generate_constant_velocity_scan.

    Parameters:
        conctimes (list): Times starting at 0 for the ACU to reach
            associated positions
        concaz (list): Azimuth positions associated with conctimes
        concel (list): Elevation positions associated with conctimes
        concva (list): Azimuth velocities associated with conctimes
        concve (list): Elevation velocities associated with conctimes
        az_flags (list): Flags associated with azimuth motions at
            conctimes
        el_flags (list): Flags associated with elevation motions at
            conctimes
        start_offset (float): Seconds to wait before starting the scan
        generator (bool): Toggles the start time. When true, start time is
            start_offset, otherwise start time is time.time() + start_offset

    Returns:
        list: Lines in the correct format to upload to the ACU
    """

    fmt = '%j, %H:%M:%S'
    if generator:
        start_time = start_offset
    else:
        start_time = time.time() + start_offset
    true_times = [start_time + i for i in conctimes]
    fmt_times = [time.strftime(fmt, time.gmtime(t))
                 + ('{tt:.6f}'.format(tt=t % 1.))[1:] for t in true_times]

    all_lines = [('{ftime}; {az:.6f}; {el:.6f}; {azvel:.4f}; '
                  '{elvel:.4f}; {azflag}; {elflag}'
                  '\r\n'.format(ftime=fmt_times[n], az=concaz[n],
                                el=concel[n], azvel=concva[n], elvel=concve[n],
                                azflag=az_flags[n], elflag=el_flags[n]))
                 for n in range(len(fmt_times))]

    return all_lines


def generate_constant_velocity_scan(az_endpoint1, az_endpoint2, az_speed,
                                    acc, el_endpoint1, el_endpoint2,
                                    el_speed,
                                    num_batches=None,
                                    num_scans=None,
                                    start_time=None,
                                    wait_to_start=10.,
                                    step_time=1.,
                                    batch_size=500,
                                    az_start='mid_inc',
                                    ramp_up=None,
                                    ptstack_fmt=True):
    """Python generator to produce times, azimuth and elevation positions,
    azimuth and elevation velocities, azimuth and elevation flags for
    arbitrarily long constant-velocity azimuth scans.

    Parameters:
        az_endpoint1 (float): azimuth endpoint for the scan start
        az_endpoint2 (float): second azimuth endpoint of the scan
        az_speed (float): speed of the constant-velocity azimuth motion
        acc (float): turnaround acceleration for the azimuth motion at the
            endpoints
        el_endpoint1 (float): elevation endpoint for the scan start
        el_endpoint2 (float): second elevation endpoint of the scan. For
            constant az scans, this must be equal to el_endpoint1.
        el_speed (float): speed of the elevation motion. For constant az
            scans, set to 0.0
        num_scans (int or None): if not None, limits the points
          returned to the specified number of constant velocity legs.
        num_batches (int or None): sets the number of batches for the
            generator to create. Default value is None (interpreted as infinite
            batches).
        start_time (float or None): a ctime at which to start the scan.
            Default is None, which is interpreted as starting now +
            wait_to_start.
        wait_to_start (float): number of seconds to wait between
            start_time and when the scan actually starts. Default is 10 seconds.
        step_time (float): time between points on the constant-velocity
            parts of the motion. Default value is 1.0 seconds. Minimum value is
            0.05 seconds.
        batch_size (int): number of values to produce in each iteration.
            Default is 500. Batch size is reset to the length of one leg of the
            motion if num_batches is not None.
        az_start (str): part of the scan to start at. Options are:
            'az_endpoint1', 'az_endpoint2', 'mid_inc' (start in the middle of
            the scan and start with increasing azimuth), 'mid_dec' (start in
            the middle of the scan and start with decreasing azimuth).
        ramp_up (float or None): make the first scan leg longer, by
            this number of degrees, on the starting end.  This is used
            to help the servo match the first leg velocity smoothly
            before it has to start worrying about the first
            turn-around.
        ptstack_fmt (bool): determine whether values are produced with the
            necessary format to upload to the ACU. If False, this function will
            produce lists of time, azimuth, elevation, azimuth velocity,
            elevation velocity, azimuth flags, and elevation flags. Default is
            True.

    """
    az_min = min(az_endpoint1, az_endpoint2)
    az_max = max(az_endpoint1, az_endpoint2)
    if az_max == az_min:
        raise ValueError('Generator requires two different az endpoints!')
    if az_start in ['az_endpoint1', 'az_endpoint2']:
        if az_start == 'az_endpoint1':
            az = az_endpoint1
        else:
            az = az_endpoint2
        if az == az_min:
            increasing = True
            az_vel = az_speed
        elif az == az_max:
            increasing = False
            az_vel = -1 * az_speed
    elif az_start in ['mid_inc', 'mid_dec']:
        az = (az_endpoint1 + az_endpoint2) / 2
        if az_start == 'mid_inc':
            increasing = True
            az_vel = az_speed
        else:
            increasing = False
            az_vel = -1 * az_speed
    else:
        raise ValueError('az_start value not supported. Choose from '
                         'az_endpoint1, az_endpoint2, mid_inc, mid_dec')

    # Bias the starting point for the first leg?
    if ramp_up is not None:
        if increasing:
            az -= ramp_up
        else:
            az += ramp_up

    if start_time is None:
        t0 = time.time() + wait_to_start
    else:
        t0 = start_time
    t = 0
    turntime = 2.0 * az_speed / acc
    el = el_endpoint1
    if step_time < 0.05:
        raise ValueError('Time step size too small, must be at least '
                         '0.05 seconds')
    daz = step_time * az_speed
    el_vel = el_speed
    az_flag = 0
    el_flag = 0
    if num_batches is None:
        stop_iter = float('inf')
    else:
        stop_iter = num_batches
        batch_size = int(np.ceil((az_max - az_min) / daz))

    def dec_num_scans():
        nonlocal num_scans
        if num_scans is not None:
            num_scans -= 1

    def check_num_scans():
        return num_scans is None or num_scans > 0

    i = 0
    while i < stop_iter and check_num_scans():
        i += 1
        point_block = [[], [], [], [], [], [], []]
        for j in range(batch_size):
            point_block[0].append(t + t0)
            point_block[1].append(az)
            point_block[2].append(el)
            point_block[3].append(az_vel)
            point_block[4].append(el_vel)
            point_block[5].append(az_flag)
            point_block[6].append(el_flag)
            t += step_time

            if increasing:
                if az <= (az_max - 2 * daz):
                    az += daz
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                elif az == az_max:
                    t += turntime
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                    dec_num_scans()
                else:
                    az_remaining = az_max - az
                    time_remaining = az_remaining / az_speed
                    az = az_max
                    t += (time_remaining - step_time)
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = True
            else:
                if az >= (az_min + 2 * daz):
                    az -= daz
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = False
                elif az == az_min:
                    t += turntime
                    az_vel = az_speed
                    el_vel = el_speed
                    az_flag = 1
                    el_flag = 0
                    increasing = True
                    dec_num_scans()
                else:
                    az_remaining = az - az_min
                    time_remaining = az_remaining / az_speed
                    az = az_min
                    t += (time_remaining - step_time)
                    az_vel = -1 * az_speed
                    el_vel = el_speed
                    az_flag = 2
                    el_flag = 0
                    increasing = False

            if not check_num_scans():
                # Kill the velocity on the last point and exit -- this
                # was recommended at LAT FAT for smoothly stopping the
                # motino at end of program.
                point_block[3][-1] = 0
                point_block[4][-1] = 0
                break

        if ptstack_fmt:
            yield ptstack_format(point_block[0], point_block[1],
                                 point_block[2], point_block[3],
                                 point_block[4], point_block[5],
                                 point_block[6], generator=True)
        else:
            yield (point_block[0], point_block[1], point_block[2],
                   point_block[3], point_block[4], point_block[5],
                   point_block[6])


def plan_scan(az_end1, az_end2, el, v_az=1, a_az=1, az_start=None):
    """Determine some important parameters for running a ProgramTrack
    scan with the desired end points, velocity, and mean turn-around
    acceleration.

    """
    # Convert Agent-friendly arguments to az/throw/init
    if az_start in [None, 'mid', 'mid_inc', 'mid_dec']:
        init = 'mid'
    else:
        init = 'end'
    az = (az_end1 + az_end2) / 2
    throw = (az_end2 - az_end1) / 2

    # Info to pass back.
    plan = {}

    # Point time separation: at least 5 points per leg, preferably 10.
    dt = 2 * abs(throw / v_az) / 10
    dt = min(max(dt, 0.1), 1.0)
    assert (2 * abs(throw / v_az) / dt >= 5)
    plan['step_time'] = dt

    # Turn around prep distance? 5 point periods, times the vel.
    az_prep = 5 * dt * v_az

    # Ramp-up distance needed
    a0 = 1.  # Peak accel of ramp-up...
    az_rampup = v_az**2 / a0
    plan['az_prep'] = az_prep
    plan['az_rampup'] = az_rampup

    # Any az ramp-up prep required?
    if init == 'mid':
        ramp_up = max(az_prep + az_rampup - abs(throw), 0)
    elif init == 'end':
        ramp_up = max(az_prep + az_rampup - 2 * abs(throw), 0)
    plan['ramp_up'] = ramp_up

    # Set wait time (this comes out a little lower than its supposed to...)
    # plan['wait_time'] = v_az / a0 * 2
    plan['pre_time'] = v_az / a0
    plan['wait_to_start'] = max(5, plan['pre_time'] * 1.2)

    # Fill out some other useful info...
    plan['init_az'] = az - math.copysign(ramp_up, throw)
    if init == 'end':
        plan['init_az'] -= throw

    return plan
